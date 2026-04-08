"""Tests for subprocess backend lifecycle events."""

from __future__ import annotations

from pathlib import Path

import pytest

from openharness.swarm.event_store import EventStore, get_event_store
from openharness.swarm.events import new_swarm_event
from openharness.swarm.subprocess_backend import SubprocessBackend
from openharness.swarm.types import TeammateMessage, TeammateSpawnConfig
from openharness.tasks.types import TaskRecord


@pytest.mark.asyncio
async def test_subprocess_backend_spawn_emits_running_event(tmp_path: Path, monkeypatch):
    store = get_event_store()
    store.clear()

    class FakeManager:
        async def create_shell_task(self, **kwargs):
            return TaskRecord(
                id="task-123",
                type="in_process_teammate",
                status="running",
                description=kwargs["description"],
                cwd=str(tmp_path),
                output_file=tmp_path / "task.log",
                command=kwargs["command"],
            )

        def get_task(self, task_id):
            del task_id
            return None

    monkeypatch.setattr("openharness.swarm.subprocess_backend.get_task_manager", lambda: FakeManager())
    monkeypatch.setattr("openharness.swarm.subprocess_backend.get_teammate_command", lambda: "openharness")
    backend = SubprocessBackend()

    result = await backend.spawn(
        TeammateSpawnConfig(
            name="worker",
            team="demo",
            prompt="do work",
            cwd=str(tmp_path),
            parent_session_id="root-session",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            lineage_path=["leader@demo"],
        )
    )

    assert result.success is True
    assert [event.event_type for event in store.events_for_agent("worker@demo")] == [
        "agent_became_running"
    ]


@pytest.mark.asyncio
async def test_subprocess_backend_persistent_spawn_disables_child_web_console(tmp_path: Path, monkeypatch):
    captured: dict[str, str] = {}

    class FakeManager:
        async def create_agent_task(self, **kwargs):
            captured["command"] = kwargs["command"]
            return TaskRecord(
                id="task-456",
                type="in_process_teammate",
                status="running",
                description=kwargs["description"],
                cwd=str(tmp_path),
                output_file=tmp_path / "task.log",
                command=kwargs["command"],
            )

        def get_task(self, task_id):
            del task_id
            return None

    monkeypatch.setenv("OPENHARNESS_OPEN_WEB_CONSOLE", "1")
    monkeypatch.setattr("openharness.swarm.subprocess_backend.get_task_manager", lambda: FakeManager())
    monkeypatch.setattr("openharness.swarm.subprocess_backend.get_teammate_command", lambda: "openharness")

    backend = SubprocessBackend()
    result = await backend.spawn(
        TeammateSpawnConfig(
            name="worker",
            team="demo",
            prompt="do work",
            cwd=str(tmp_path),
            spawn_mode="persistent",
            parent_session_id="root-session",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            lineage_path=["leader@demo"],
        )
    )

    assert result.success is True
    assert "OPENHARNESS_DISABLE_SHARED_WEB='1'" in captured["command"]
    assert "OPENHARNESS_OPEN_WEB_CONSOLE='0'" in captured["command"]


@pytest.mark.asyncio
async def test_subprocess_backend_notify_completion_emits_finished_event(tmp_path: Path, monkeypatch):
    store = get_event_store()
    store.clear()

    class FakeManager:
        def get_task(self, task_id):
            return TaskRecord(
                id=task_id,
                type="in_process_teammate",
                status="completed",
                description="demo",
                cwd=str(tmp_path),
                output_file=tmp_path / "task.log",
            )

    monkeypatch.setattr("openharness.swarm.subprocess_backend.get_task_manager", lambda: FakeManager())
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    backend = SubprocessBackend()
    await backend._notify_leader_on_completion(
        "task-123",
        "worker@demo",
        "demo",
        "leader@demo",
        "leader@demo",
        "worker-session",
    )

    assert [event.event_type for event in store.events_for_agent("worker@demo")] == [
        "agent_finished"
    ]


@pytest.mark.asyncio
async def test_subprocess_backend_send_message_restores_task_mapping_from_spawn_event(tmp_path: Path, monkeypatch):
    store = EventStore()
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            payload={"backend_type": "subprocess", "task_id": "task-123", "spawn_mode": "persistent"},
        )
    )

    writes: list[tuple[str, str]] = []

    class FakeManager:
        async def write_to_task(self, task_id, data):
            writes.append((task_id, data))

    monkeypatch.setattr("openharness.swarm.subprocess_backend.get_event_store", lambda: store)
    monkeypatch.setattr("openharness.swarm.subprocess_backend.get_task_manager", lambda: FakeManager())
    monkeypatch.setattr(
        "openharness.swarm.subprocess_backend.load_persisted_task_record",
        lambda task_id: TaskRecord(
            id=task_id,
            type="in_process_teammate",
            status="running",
            description="demo",
            cwd=str(tmp_path),
            output_file=tmp_path / "task.log",
            command="python -m openharness --backend-only",
        ),
    )
    backend = SubprocessBackend()

    await backend.send_message("worker@demo", TeammateMessage(text="ping", from_agent="leader"))

    assert writes == [("task-123", '{"type": "submit_line", "line": "ping"}')]
