"""Shared helpers for delegated agent background tasks (same scope as ``/agents``)."""

from __future__ import annotations

from pathlib import Path

from openharness.tasks import get_task_manager
from openharness.tasks.manager import BackgroundTaskManager, _pid_points_to_live_process
from openharness.tasks.types import TaskRecord, TaskType

# Subprocess / remote / in-process teammate rows — matches ``/agents`` listing.
AGENT_TASK_TYPES: frozenset[TaskType] = frozenset(
    {"local_agent", "remote_agent", "in_process_teammate"}
)

# Same cap as ``/agents all`` for readable listings and UI payloads.
AGENT_TASK_LIST_CAP = 80


def resolved_cwd(cwd: str | Path) -> str:
    return str(Path(cwd).resolve())


def list_agent_tasks_for_cwd(
    *,
    cwd: str | Path,
    running_only: bool = False,
    cap: int | None = AGENT_TASK_LIST_CAP,
    manager: BackgroundTaskManager | None = None,
) -> list[TaskRecord]:
    """Agent-type tasks for *cwd*, newest first (aligned with ``/agents``)."""
    m = manager or get_task_manager()
    want = resolved_cwd(cwd)
    tasks = [
        t
        for t in m.list_tasks()
        if t.type in AGENT_TASK_TYPES and resolved_cwd(t.cwd) == want
    ]
    if running_only:
        tasks = [t for t in tasks if t.status == "running" and _task_record_has_live_pid(t)]
    tasks.sort(key=lambda t: t.created_at, reverse=True)
    if cap is not None:
        tasks = tasks[:cap]
    return tasks


def count_agent_tasks_for_cwd(
    *,
    cwd: str | Path,
    running_only: bool = False,
    manager: BackgroundTaskManager | None = None,
) -> int:
    """Uncapped count for status bar / summaries (same filter as ``/agents all``)."""
    m = manager or get_task_manager()
    want = resolved_cwd(cwd)
    n = 0
    for t in m.list_tasks():
        if t.type not in AGENT_TASK_TYPES or resolved_cwd(t.cwd) != want:
            continue
        if running_only and (t.status != "running" or not _task_record_has_live_pid(t)):
            continue
        n += 1
    return n


def _task_record_has_live_pid(task: TaskRecord) -> bool:
    pid = int(task.metadata.get("pid", "0") or "0")
    return _pid_points_to_live_process(pid)


def clear_finished_agent_task_records(
    manager: BackgroundTaskManager,
    *,
    cwd: str | None = None,
) -> list[str]:
    """Remove terminal *agent* task rows only (``/agents clear all|here``)."""
    return manager.clear_finished_task_records(cwd=cwd, task_types=AGENT_TASK_TYPES)


def remove_finished_agent_task_record(
    manager: BackgroundTaskManager,
    task_id: str,
    *,
    cwd: str | Path,
) -> str:
    """Remove one terminal agent-task record in this project cwd (``/agents clear <id>``)."""
    return manager.remove_finished_task_record(
        task_id,
        cwd=resolved_cwd(cwd),
        task_types=AGENT_TASK_TYPES,
    )


def purge_stale_agent_task_records(
    manager: BackgroundTaskManager,
    *,
    cwd: str | Path,
) -> list[str]:
    """Drop orphan ``running`` agent rows whose child PID is dead (``/agents clear stale``)."""
    return manager.purge_stale_running_task_records(
        cwd=resolved_cwd(cwd),
        task_types=AGENT_TASK_TYPES,
    )
