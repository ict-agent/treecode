"""Background task manager."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import signal
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from openharness.config.paths import get_tasks_dir
from openharness.tasks.types import TaskRecord, TaskStatus, TaskType


class BackgroundTaskManager:
    """Manage shell and agent subprocess tasks."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._waiters: dict[str, asyncio.Task[None]] = {}
        self._output_locks: dict[str, asyncio.Lock] = {}
        self._input_locks: dict[str, asyncio.Lock] = {}
        self._generations: dict[str, int] = {}

    async def create_shell_task(
        self,
        *,
        command: str,
        description: str,
        cwd: str | Path,
        task_type: TaskType = "local_bash",
    ) -> TaskRecord:
        """Start a background shell command."""
        task_id = _task_id(task_type)
        output_path = get_tasks_dir() / f"{task_id}.log"
        record = TaskRecord(
            id=task_id,
            type=task_type,
            status="running",
            description=description,
            cwd=str(Path(cwd).resolve()),
            output_file=output_path,
            command=command,
            created_at=time.time(),
            started_at=time.time(),
        )
        output_path.write_text("", encoding="utf-8")
        self._tasks[task_id] = record
        self._output_locks[task_id] = asyncio.Lock()
        self._input_locks[task_id] = asyncio.Lock()
        await self._start_process(task_id)
        self._persist_task(task_id)
        return record

    async def create_agent_task(
        self,
        *,
        prompt: str,
        description: str,
        cwd: str | Path,
        task_type: TaskType = "local_agent",
        model: str | None = None,
        api_key: str | None = None,
        command: str | None = None,
    ) -> TaskRecord:
        """Start a local agent task as a subprocess."""
        if command is None:
            effective_api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not effective_api_key:
                raise ValueError(
                    "Local agent tasks require ANTHROPIC_API_KEY or an explicit command override"
                )
            # Use --backend-only for non-interactive operation (agent uses stdin/stdout for prompts)
            cmd = ["python", "-m", "openharness", "--backend-only", "--api-key", effective_api_key]
            if model:
                cmd.extend(["--model", model])
            command = " ".join(shlex.quote(part) for part in cmd)

        record = await self.create_shell_task(
            command=command,
            description=description,
            cwd=cwd,
            task_type=task_type,
        )
        updated = replace(record, prompt=prompt)
        if task_type != "local_agent":
            updated.metadata["agent_mode"] = task_type
        self._tasks[record.id] = updated
        import json as _json
        await self.write_to_task(
            record.id,
            _json.dumps({"type": "submit_line", "line": prompt}),
        )
        return updated

    def get_task(self, task_id: str) -> TaskRecord | None:
        """Return one task record.

        Falls back to :func:`load_persisted_task_record` so callers in a *different*
        process than the one that created the task (nested agent subprocesses) still
        see the same tasks as ``tasks_snapshot`` / ``task_list`` (disk-backed).
        """
        task = self._tasks.get(task_id)
        if task is not None:
            return task
        task = load_persisted_task_record(task_id)
        if task is not None:
            self._tasks.setdefault(task_id, task)
            self._output_locks.setdefault(task_id, asyncio.Lock())
            self._input_locks.setdefault(task_id, asyncio.Lock())
        return task

    def list_tasks(self, *, status: TaskStatus | None = None) -> list[TaskRecord]:
        """Return all tasks, optionally filtered by status.

        Merges in-memory tasks with ``*.json`` records under the tasks directory so
        tasks created by other processes (each with its own manager instance) appear
        in ``task_list`` / UI snapshots consistently with ``task_get``.
        """
        by_id: dict[str, TaskRecord] = dict(self._tasks)
        for path in get_tasks_dir().glob("*.json"):
            tid = path.stem
            if tid in by_id:
                continue
            loaded = load_persisted_task_record(tid)
            if loaded is not None:
                by_id[tid] = loaded
        tasks = list(by_id.values())
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        return sorted(tasks, key=lambda item: item.created_at, reverse=True)

    def update_task(
        self,
        task_id: str,
        *,
        description: str | None = None,
        progress: int | None = None,
        status_note: str | None = None,
    ) -> TaskRecord:
        """Update mutable task metadata used for coordination and UI display."""
        task = self._require_task(task_id)
        if description is not None and description.strip():
            task.description = description.strip()
        if progress is not None:
            task.metadata["progress"] = str(progress)
        if status_note is not None:
            note = status_note.strip()
            if note:
                task.metadata["status_note"] = note
            else:
                task.metadata.pop("status_note", None)
        self._persist_task(task_id)
        return task

    async def stop_task(self, task_id: str) -> TaskRecord:
        """Terminate a running task."""
        task = self._tasks.get(task_id) or load_persisted_task_record(task_id)
        if task is None:
            raise ValueError(f"No task found with ID: {task_id}")
        self._tasks.setdefault(task_id, task)
        process = self._processes.get(task_id)
        if process is None:
            if task.status in {"completed", "failed", "killed"}:
                return task
            pid = int(task.metadata.get("pid", "0") or "0")
            if pid <= 0:
                raise ValueError(f"Task {task_id} is not running")
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
            task.status = "killed"
            task.ended_at = time.time()
            self._persist_task(task_id)
            return task

        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

        task.status = "killed"
        task.ended_at = time.time()
        self._persist_task(task_id)
        return task

    async def pause_task(self, task_id: str) -> TaskRecord:
        """Pause a running task using ``SIGSTOP`` on POSIX systems."""
        task = self._tasks.get(task_id) or load_persisted_task_record(task_id)
        if task is None:
            raise ValueError(f"No task found with ID: {task_id}")
        self._tasks.setdefault(task_id, task)
        process = self._processes.get(task_id)
        pid = process.pid if process is not None and process.returncode is None else int(
            task.metadata.get("pid", "0") or "0"
        )
        if pid <= 0:
            raise ValueError(f"Task {task_id} is not running")
        os.kill(pid, signal.SIGSTOP)
        task.metadata["paused"] = "true"
        self._persist_task(task_id)
        return task

    async def resume_task(self, task_id: str) -> TaskRecord:
        """Resume a paused task using ``SIGCONT`` on POSIX systems."""
        task = self._tasks.get(task_id) or load_persisted_task_record(task_id)
        if task is None:
            raise ValueError(f"No task found with ID: {task_id}")
        self._tasks.setdefault(task_id, task)
        process = self._processes.get(task_id)
        pid = process.pid if process is not None and process.returncode is None else int(
            task.metadata.get("pid", "0") or "0"
        )
        if pid <= 0:
            raise ValueError(f"Task {task_id} is not running")
        os.kill(pid, signal.SIGCONT)
        task.metadata["paused"] = "false"
        self._persist_task(task_id)
        return task

    async def write_to_task(self, task_id: str, data: str) -> None:
        """Write one line to task stdin, auto-resuming local agents when needed."""
        task = self._require_task(task_id)
        async with self._input_locks[task_id]:
            process = await self._ensure_writable_process(task)
            process.stdin.write((data.rstrip("\n") + "\n").encode("utf-8"))
            try:
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                if task.type not in {"local_agent", "remote_agent", "in_process_teammate"}:
                    raise ValueError(f"Task {task_id} does not accept input") from None
                process = await self._restart_agent_task(task)
                process.stdin.write((data.rstrip("\n") + "\n").encode("utf-8"))
                await process.stdin.drain()

    def read_task_output(self, task_id: str, *, max_bytes: int = 12000) -> str:
        """Return the tail of a task's output file."""
        task = self._require_task(task_id)
        content = task.output_file.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_bytes:
            return content[-max_bytes:]
        return content

    async def _watch_process(
        self,
        task_id: str,
        process: asyncio.subprocess.Process,
        generation: int,
    ) -> None:
        reader = asyncio.create_task(self._copy_output(task_id, process))
        return_code = await process.wait()
        await reader

        current_generation = self._generations.get(task_id)
        if current_generation != generation:
            return

        task = self._tasks[task_id]
        task.return_code = return_code
        if task.status != "killed":
            task.status = "completed" if return_code == 0 else "failed"
        task.ended_at = time.time()
        self._processes.pop(task_id, None)
        self._waiters.pop(task_id, None)
        self._persist_task(task_id)

    async def _copy_output(self, task_id: str, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None:
            return
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                return
            async with self._output_locks[task_id]:
                with self._tasks[task_id].output_file.open("ab") as handle:
                    handle.write(chunk)

    def _require_task(self, task_id: str) -> TaskRecord:
        task = self._tasks.get(task_id)
        if task is None:
            task = load_persisted_task_record(task_id)
            if task is not None:
                self._tasks[task_id] = task
                self._output_locks.setdefault(task_id, asyncio.Lock())
                self._input_locks.setdefault(task_id, asyncio.Lock())
        if task is None:
            raise ValueError(f"No task found with ID: {task_id}")
        return task

    async def _start_process(self, task_id: str) -> asyncio.subprocess.Process:
        task = self._require_task(task_id)
        if task.command is None:
            raise ValueError(f"Task {task_id} does not have a command to run")

        generation = self._generations.get(task_id, 0) + 1
        self._generations[task_id] = generation
        process = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-lc",
            task.command,
            cwd=task.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._processes[task_id] = process
        task.metadata["pid"] = str(process.pid)
        self._waiters[task_id] = asyncio.create_task(
            self._watch_process(task_id, process, generation)
        )
        self._persist_task(task_id)
        return process

    async def _ensure_writable_process(
        self,
        task: TaskRecord,
    ) -> asyncio.subprocess.Process:
        process = self._processes.get(task.id)
        if process is not None and process.stdin is not None and process.returncode is None:
            return process
        if task.type not in {"local_agent", "remote_agent", "in_process_teammate"}:
            raise ValueError(f"Task {task.id} does not accept input")
        return await self._restart_agent_task(task)

    async def _restart_agent_task(self, task: TaskRecord) -> asyncio.subprocess.Process:
        if task.command is None:
            raise ValueError(f"Task {task.id} does not have a restart command")

        waiter = self._waiters.get(task.id)
        if waiter is not None and not waiter.done():
            await waiter

        restart_count = int(task.metadata.get("restart_count", "0")) + 1
        task.metadata["restart_count"] = str(restart_count)
        task.status = "running"
        task.started_at = time.time()
        task.ended_at = None
        task.return_code = None
        return await self._start_process(task.id)

    def _persist_task(self, task_id: str) -> None:
        task = self._require_task(task_id)
        _task_record_path(task_id).write_text(json.dumps(task.to_dict()), encoding="utf-8")


_DEFAULT_MANAGER: BackgroundTaskManager | None = None
_DEFAULT_MANAGER_KEY: str | None = None


def get_task_manager() -> BackgroundTaskManager:
    """Return the singleton task manager."""
    global _DEFAULT_MANAGER, _DEFAULT_MANAGER_KEY
    current_key = str(get_tasks_dir().resolve())
    if _DEFAULT_MANAGER is None or _DEFAULT_MANAGER_KEY != current_key:
        _DEFAULT_MANAGER = BackgroundTaskManager()
        _DEFAULT_MANAGER_KEY = current_key
    return _DEFAULT_MANAGER


def _task_id(task_type: TaskType) -> str:
    prefixes = {
        "local_bash": "b",
        "local_agent": "a",
        "remote_agent": "r",
        "in_process_teammate": "t",
    }
    return f"{prefixes[task_type]}{uuid4().hex[:8]}"


def _task_record_path(task_id: str) -> Path:
    return get_tasks_dir() / f"{task_id}.json"


def load_persisted_task_record(task_id: str) -> TaskRecord | None:
    """Load a persisted task record for cross-process inspection/control."""
    path = _task_record_path(task_id)
    if not path.exists():
        return None
    return TaskRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
