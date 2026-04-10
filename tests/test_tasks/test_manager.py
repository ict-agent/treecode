"""Tests for background task management."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from treecode.tasks.agent_tasks import AGENT_TASK_TYPES
from treecode.tasks.manager import BackgroundTaskManager, load_persisted_task_record
from treecode.tasks.types import TaskRecord


@pytest.mark.asyncio
async def test_create_shell_task_and_read_output(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="printf 'hello task'",
        description="hello",
        cwd=tmp_path,
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "completed"
    assert "hello task" in manager.read_task_output(task.id)


@pytest.mark.asyncio
async def test_create_agent_task_with_command_override_and_write(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="first",
        description="agent",
        cwd=tmp_path,
        command="while read line; do echo \"got:$line\"; break; done",
    )

    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    # create_agent_task wraps the prompt as {"type":"submit_line","line":"..."} protocol
    assert '"line": "first"' in manager.read_task_output(task.id)


@pytest.mark.asyncio
async def test_write_to_stopped_agent_task_restarts_process(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="ready",
        description="agent",
        cwd=tmp_path,
        command="while read line; do echo \"got:$line\"; break; done",
    )
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    await manager.write_to_task(task.id, "follow-up")
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    output = manager.read_task_output(task.id)
    # create_agent_task wraps the prompt as {"type":"submit_line","line":"..."} protocol
    assert '"line": "ready"' in output
    assert "got:follow-up" in output
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.metadata["restart_count"] == "1"


@pytest.mark.asyncio
async def test_write_to_persisted_agent_task_reloads_record_after_manager_restart(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_agent_task(
        prompt="ready",
        description="agent",
        cwd=tmp_path,
        command="while read line; do echo \"got:$line\"; break; done",
    )
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    reloaded_manager = BackgroundTaskManager()
    await reloaded_manager.write_to_task(task.id, "follow-up")
    await asyncio.wait_for(reloaded_manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    output = reloaded_manager.read_task_output(task.id)
    assert '"line": "ready"' in output
    assert "got:follow-up" in output


@pytest.mark.asyncio
async def test_get_task_loads_from_disk_when_not_in_memory(tmp_path: Path, monkeypatch):
    """Simulates parent vs nested-agent process: only JSON exists on the shared data dir."""
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    creator = BackgroundTaskManager()
    task = await creator.create_shell_task(
        command="printf 'disk-visible'",
        description="nested",
        cwd=tmp_path,
    )
    await asyncio.wait_for(creator._waiters[task.id], timeout=5)  # type: ignore[attr-defined]
    assert load_persisted_task_record(task.id) is not None

    other_process = BackgroundTaskManager()
    assert task.id not in other_process._tasks
    loaded = other_process.get_task(task.id)
    assert loaded is not None
    assert loaded.id == task.id
    assert loaded.description == "nested"


@pytest.mark.asyncio
async def test_list_tasks_merges_persisted_tasks_from_shared_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    m_a = BackgroundTaskManager()
    t_a = await m_a.create_shell_task(
        command="printf a",
        description="from-a",
        cwd=tmp_path,
    )
    await asyncio.wait_for(m_a._waiters[t_a.id], timeout=5)  # type: ignore[attr-defined]

    m_b = BackgroundTaskManager()
    t_b = await m_b.create_shell_task(
        command="printf b",
        description="from-b",
        cwd=tmp_path,
    )
    await asyncio.wait_for(m_b._waiters[t_b.id], timeout=5)  # type: ignore[attr-defined]

    listed = m_b.list_tasks()
    ids = {rec.id for rec in listed}
    assert t_a.id in ids
    assert t_b.id in ids


@pytest.mark.asyncio
async def test_stop_task(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    task = await manager.create_shell_task(
        command="sleep 30",
        description="sleeper",
        cwd=tmp_path,
    )
    await manager.stop_task(task.id)
    updated = manager.get_task(task.id)
    assert updated is not None
    assert updated.status == "killed"


@pytest.mark.asyncio
async def test_clear_finished_task_records_respects_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    a = tmp_path / "proj_a"
    b = tmp_path / "proj_b"
    a.mkdir()
    b.mkdir()

    ma = BackgroundTaskManager()
    mb = BackgroundTaskManager()

    t_a = await ma.create_shell_task(command="printf a", description="a", cwd=a)
    await asyncio.wait_for(ma._waiters[t_a.id], timeout=5)  # type: ignore[attr-defined]
    t_b = await mb.create_shell_task(command="printf b", description="b", cwd=b)
    await asyncio.wait_for(mb._waiters[t_b.id], timeout=5)  # type: ignore[attr-defined]

    cleared = BackgroundTaskManager().clear_finished_task_records(cwd=str(a.resolve()))
    assert t_a.id in cleared
    assert t_b.id not in cleared
    assert load_persisted_task_record(t_a.id) is None
    assert load_persisted_task_record(t_b.id) is not None

    rest = BackgroundTaskManager().clear_finished_task_records()
    assert t_b.id in rest
    assert load_persisted_task_record(t_b.id) is None


@pytest.mark.asyncio
async def test_clear_finished_task_records_task_types_filter(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()

    shell_done = await manager.create_shell_task(command="printf x", description="sh", cwd=tmp_path)
    await asyncio.wait_for(manager._waiters[shell_done.id], timeout=5)  # type: ignore[attr-defined]

    agent = await manager.create_agent_task(
        prompt="x",
        description="ag",
        cwd=tmp_path,
        command="python -u -c \"import sys; print(sys.stdin.readline())\"",
    )
    await asyncio.wait_for(manager._waiters[agent.id], timeout=5)  # type: ignore[attr-defined]

    cleared = BackgroundTaskManager().clear_finished_task_records(task_types=AGENT_TASK_TYPES)
    assert agent.id in cleared
    assert shell_done.id not in cleared
    assert load_persisted_task_record(shell_done.id) is not None

    rest = BackgroundTaskManager().clear_finished_task_records()
    assert shell_done.id in rest


@pytest.mark.asyncio
async def test_remove_finished_task_record_single(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()
    task = await manager.create_shell_task(command="printf x", description="one", cwd=tmp_path)
    await asyncio.wait_for(manager._waiters[task.id], timeout=5)  # type: ignore[attr-defined]

    m2 = BackgroundTaskManager()
    m2.remove_finished_task_record(task.id, cwd=str(tmp_path.resolve()))
    assert load_persisted_task_record(task.id) is None


def test_purge_stale_running_task_records_drops_dead_pid_only(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    from treecode.config.paths import get_tasks_dir

    tasks_dir = get_tasks_dir()
    tasks_dir.mkdir(parents=True, exist_ok=True)
    cwd = str(tmp_path.resolve())

    ghost_log = tasks_dir / "ghost.log"
    ghost_log.write_text("", encoding="utf-8")
    ghost = TaskRecord(
        id="bghost000",
        type="local_bash",
        status="running",
        description="ghost",
        cwd=cwd,
        output_file=ghost_log,
        metadata={"pid": str(2**30)},
        created_at=0.0,
    )
    (tasks_dir / f"{ghost.id}.json").write_text(json.dumps(ghost.to_dict()), encoding="utf-8")

    alive_log = tasks_dir / "alive.log"
    alive_log.write_text("", encoding="utf-8")
    alive = TaskRecord(
        id="balive000",
        type="local_bash",
        status="running",
        description="alive",
        cwd=cwd,
        output_file=alive_log,
        metadata={"pid": str(os.getpid())},
        created_at=0.0,
    )
    (tasks_dir / f"{alive.id}.json").write_text(json.dumps(alive.to_dict()), encoding="utf-8")

    removed = BackgroundTaskManager().purge_stale_running_task_records(cwd=cwd)
    assert ghost.id in removed
    assert alive.id not in removed
    assert load_persisted_task_record(ghost.id) is None
    assert load_persisted_task_record(alive.id) is not None


@pytest.mark.asyncio
async def test_remove_finished_task_record_rejects_running(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    manager = BackgroundTaskManager()
    task = await manager.create_shell_task(command="sleep 60", description="run", cwd=tmp_path)
    with pytest.raises(ValueError, match="still active"):
        manager.remove_finished_task_record(task.id, cwd=str(tmp_path.resolve()))
    await manager.stop_task(task.id)
