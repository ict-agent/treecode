"""Tests for task and team tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from openharness.swarm.context_registry import AgentContextRegistry
from openharness.swarm.event_store import get_event_store
from openharness.tasks.manager import load_persisted_task_record
from openharness.tasks import get_task_manager
from openharness.coordinator.coordinator_mode import TeamRegistry
from openharness.tools.agent_tool import AgentTool, AgentToolInput
from openharness.tools.base import ToolExecutionContext
from openharness.tools.task_create_tool import TaskCreateTool, TaskCreateToolInput
from openharness.tools.task_output_tool import TaskOutputTool, TaskOutputToolInput
from openharness.tools.task_update_tool import TaskUpdateTool, TaskUpdateToolInput
from openharness.tools.team_create_tool import TeamCreateTool, TeamCreateToolInput


@pytest.mark.asyncio
async def test_task_create_and_output_tool(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    context = ToolExecutionContext(cwd=tmp_path)

    create_result = await TaskCreateTool().execute(
        TaskCreateToolInput(
            type="local_bash",
            description="echo",
            command="printf 'tool task'",
        ),
        context,
    )
    assert create_result.is_error is False
    task_id = create_result.output.split()[2]

    manager = get_task_manager()
    for _ in range(20):
        if "tool task" in manager.read_task_output(task_id):
            break
        await asyncio.sleep(0.1)
    output_result = await TaskOutputTool().execute(
        TaskOutputToolInput(task_id=task_id),
        context,
    )
    assert "tool task" in output_result.output


@pytest.mark.asyncio
async def test_team_create_tool(tmp_path: Path):
    result = await TeamCreateTool().execute(
        TeamCreateToolInput(name="demo", description="test"),
        ToolExecutionContext(cwd=tmp_path),
    )
    assert result.is_error is False
    assert "Created team demo" == result.output


@pytest.mark.asyncio
async def test_task_update_tool_updates_metadata(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    context = ToolExecutionContext(cwd=tmp_path)

    create_result = await TaskCreateTool().execute(
        TaskCreateToolInput(
            type="local_bash",
            description="updatable",
            command="printf 'tool task'",
        ),
        context,
    )
    task_id = create_result.output.split()[2]

    update_result = await TaskUpdateTool().execute(
        TaskUpdateToolInput(
            task_id=task_id,
            progress=60,
            status_note="waiting on verification",
            description="renamed task",
        ),
        context,
    )
    assert update_result.is_error is False

    task = get_task_manager().get_task(task_id)
    assert task is not None
    assert task.description == "renamed task"
    assert task.metadata["progress"] == "60"
    assert task.metadata["status_note"] == "waiting on verification"


@pytest.mark.asyncio
async def test_task_manager_persists_task_record(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    context = ToolExecutionContext(cwd=tmp_path)

    create_result = await TaskCreateTool().execute(
        TaskCreateToolInput(
            type="local_bash",
            description="sleepy",
            command="python -c \"import time; time.sleep(2)\"",
        ),
        context,
    )
    task_id = create_result.output.split()[2]
    persisted = load_persisted_task_record(task_id)
    assert persisted is not None
    assert persisted.id == task_id
    assert persisted.metadata["pid"]


@pytest.mark.asyncio
async def test_agent_tool_supports_remote_and_teammate_modes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    context = ToolExecutionContext(cwd=tmp_path)

    for i, mode in enumerate(("remote_agent", "in_process_teammate")):
        result = await AgentTool().execute(
            AgentToolInput(
                description=f"{mode} smoke",
                prompt="ready",
                mode=mode,
                subagent_type=f"test-worker-{i}",
                command="python -u -c \"import sys; print(sys.stdin.readline().strip())\"",
            ),
            context,
        )
        assert result.is_error is False
        # Output format: "Spawned agent X (task_id=Y, backend=Z)"
        assert "agent" in result.output.lower() or "task_id" in result.output.lower()


@pytest.mark.asyncio
async def test_agent_tool_propagates_tree_identity_to_spawn_config(tmp_path: Path, monkeypatch):
    fresh_reg = AgentContextRegistry()
    monkeypatch.setattr("openharness.tools.agent_tool.get_context_registry", lambda: fresh_reg)
    captured = {}

    class FakeExecutor:
        type = "subprocess"

        async def spawn(self, config):
            captured["config"] = config
            from openharness.swarm.types import SpawnResult

            return SpawnResult(
                task_id="task-123",
                agent_id=f"{config.name}@{config.team}",
                backend_type="subprocess",
            )

    class FakeRegistry:
        def get_executor(self, backend_type=None):
            assert backend_type == "subprocess"
            return FakeExecutor()

    monkeypatch.setattr("openharness.tools.agent_tool.get_backend_registry", lambda: FakeRegistry())
    context = ToolExecutionContext(
        cwd=tmp_path,
        metadata={
            "session_id": "root-session",
            "swarm_agent_id": "leader@default",
            "swarm_root_agent_id": "leader@default",
            "swarm_lineage_path": ("leader@default",),
        },
    )

    result = await AgentTool().execute(
        AgentToolInput(description="spawn worker", prompt="do work", subagent_type="worker"),
        context,
    )

    assert result.is_error is False
    config = captured["config"]
    assert config.parent_session_id == "root-session"
    assert config.parent_agent_id == "leader@default"
    assert config.root_agent_id == "leader@default"
    assert config.lineage_path == ["leader@default"]


@pytest.mark.asyncio
async def test_agent_tool_emits_spawn_events(tmp_path: Path, monkeypatch):
    fresh_reg = AgentContextRegistry()
    monkeypatch.setattr("openharness.tools.agent_tool.get_context_registry", lambda: fresh_reg)
    store = get_event_store()
    store.clear()

    class FakeExecutor:
        type = "subprocess"

        async def spawn(self, config):
            from openharness.swarm.types import SpawnResult

            return SpawnResult(
                task_id="task-123",
                agent_id=f"{config.name}@{config.team}",
                backend_type="subprocess",
            )

    class FakeRegistry:
        def get_executor(self, backend_type=None):
            assert backend_type == "subprocess"
            return FakeExecutor()

    monkeypatch.setattr("openharness.tools.agent_tool.get_backend_registry", lambda: FakeRegistry())
    context = ToolExecutionContext(
        cwd=tmp_path,
        metadata={
            "session_id": "root-session",
            "swarm_agent_id": "leader@default",
            "swarm_root_agent_id": "leader@default",
            "swarm_lineage_path": ("leader@default",),
        },
    )

    result = await AgentTool().execute(
        AgentToolInput(description="spawn worker", prompt="do work", subagent_type="worker"),
        context,
    )

    assert result.is_error is False
    events = store.events_for_agent("worker@default")
    assert [event.event_type for event in events] == [
        "agent_spawn_requested",
        "agent_spawned",
        "agent_attached_to_parent",
    ]


@pytest.mark.asyncio
async def test_agent_tool_does_not_fail_when_team_not_precreated(tmp_path: Path, monkeypatch):
    fresh_reg = AgentContextRegistry()
    monkeypatch.setattr("openharness.tools.agent_tool.get_context_registry", lambda: fresh_reg)
    class FakeExecutor:
        type = "subprocess"

        async def spawn(self, config):
            from openharness.swarm.types import SpawnResult

            return SpawnResult(
                task_id="task-123",
                agent_id=f"{config.name}@{config.team}",
                backend_type="subprocess",
            )

    class FakeRegistry:
        def get_executor(self, backend_type=None):
            assert backend_type == "subprocess"
            return FakeExecutor()

    monkeypatch.setattr("openharness.tools.agent_tool.get_backend_registry", lambda: FakeRegistry())
    monkeypatch.setattr("openharness.tools.agent_tool.get_team_registry", lambda: TeamRegistry())
    result = await AgentTool().execute(
        AgentToolInput(
            description="spawn worker",
            prompt="do work",
            subagent_type="worker",
            team="default",
        ),
        ToolExecutionContext(cwd=tmp_path),
    )

    assert result.is_error is False
    assert "worker@default" in result.output


@pytest.mark.asyncio
async def test_agent_tool_reuses_distinct_swarm_id_when_same_default_name(tmp_path: Path, monkeypatch):
    """Nested agent spawns often omit subagent_type; they must not all map to agent@default."""
    reg = AgentContextRegistry()
    monkeypatch.setattr("openharness.tools.agent_tool.get_context_registry", lambda: reg)
    store = get_event_store()
    store.clear()

    class FakeExecutor:
        type = "subprocess"

        async def spawn(self, config):
            from openharness.swarm.types import SpawnResult

            return SpawnResult(
                task_id=f"task-{config.name}",
                agent_id=f"{config.name}@{config.team}",
                backend_type="subprocess",
            )

    class FakeRegistry:
        def get_executor(self, backend_type=None):
            return FakeExecutor()

    monkeypatch.setattr("openharness.tools.agent_tool.get_backend_registry", lambda: FakeRegistry())
    ctx = ToolExecutionContext(cwd=tmp_path)

    r1 = await AgentTool().execute(
        AgentToolInput(description="first", prompt="p1"),
        ctx,
    )
    r2 = await AgentTool().execute(
        AgentToolInput(description="second", prompt="p2"),
        ctx,
    )
    assert r1.is_error is False
    assert r2.is_error is False
    assert reg.get("agent@default") is not None
    assert reg.get("agent-1@default") is not None
    assert "agent-1@default" in r2.output
