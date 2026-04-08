"""Tests for background task management."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openharness.tasks.manager import BackgroundTaskManager, load_persisted_task_record


@pytest.mark.asyncio
async def test_create_shell_task_and_read_output(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
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
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
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
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
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
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
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
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
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
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
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
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
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
