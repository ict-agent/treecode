"""Tests for task and team tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from treecode.swarm.context_registry import AgentContextRegistry
from treecode.swarm.event_store import get_event_store
from treecode.tasks.manager import load_persisted_task_record
from treecode.tasks import get_task_manager
from treecode.coordinator.coordinator_mode import TeamRegistry
from treecode.tools.agent_tool import AgentTool, AgentToolInput
from treecode.tools.base import ToolExecutionContext, ToolResult
from treecode.tools.task_create_tool import TaskCreateTool, TaskCreateToolInput
from treecode.tools.task_list_tool import TaskListTool, TaskListToolInput
from treecode.tools.task_output_tool import TaskOutputTool, TaskOutputToolInput
from treecode.tools.task_update_tool import TaskUpdateTool, TaskUpdateToolInput
from treecode.tools.swarm_handshake_tool import SwarmHandshakeTool, SwarmHandshakeToolInput
from treecode.tools.team_create_tool import TeamCreateTool, TeamCreateToolInput


@pytest.mark.asyncio
async def test_task_create_and_output_tool(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
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
async def test_task_list_tool_omits_stale_running_agent_rows(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    from treecode.config.paths import get_tasks_dir
    from treecode.tasks.types import TaskRecord
    import json

    tasks_dir = get_tasks_dir()
    tasks_dir.mkdir(parents=True, exist_ok=True)
    ghost = TaskRecord(
        id="ghost-task",
        type="in_process_teammate",
        status="running",
        description="ghost",
        cwd=str(tmp_path),
        output_file=tasks_dir / "ghost-task.log",
        metadata={"pid": str(2**30)},
    )
    ghost.output_file.write_text("", encoding="utf-8")
    (tasks_dir / "ghost-task.json").write_text(json.dumps(ghost.to_dict()), encoding="utf-8")

    alive = await get_task_manager().create_agent_task(
        prompt="ready",
        description="alive agent",
        cwd=tmp_path,
        command="python -u -c \"import time; time.sleep(30)\"",
    )
    tool = TaskListTool()
    result = await tool.execute(TaskListToolInput(), ToolExecutionContext(cwd=tmp_path))
    await get_task_manager().stop_task(alive.id)

    assert "alive agent" in result.output
    assert "ghost-task" not in result.output


@pytest.mark.asyncio
async def test_swarm_handshake_tool_targets_current_live_children_and_summarizes_replies(tmp_path: Path, monkeypatch):
    from treecode.swarm.event_store import EventStore
    from treecode.swarm.events import new_swarm_event
    from treecode.tasks.types import TaskRecord

    store = EventStore()
    for agent_id, task_id in (("A@default", "task-a"), ("B@default", "task-b")):
        store.append(
            new_swarm_event(
                "agent_spawned",
                agent_id=agent_id,
                parent_agent_id="main@default",
                root_agent_id="main@default",
                session_id=agent_id,
                payload={
                    "name": agent_id.split("@", 1)[0],
                    "team": "default",
                    "backend_type": "subprocess",
                    "spawn_mode": "persistent",
                    "task_id": task_id,
                    "parent_session_id": "sess-main",
                    "lineage_path": ["main@default", agent_id],
                },
            )
        )

    monkeypatch.setattr("treecode.tools.swarm_handshake_tool.get_event_store", lambda: store)
    monkeypatch.setattr(
        "treecode.tools.swarm_handshake_tool.live_runtime_state",
        lambda _events: {
            "A@default": {"status": "running", "backend_type": "subprocess", "spawn_mode": "persistent"},
            "B@default": {"status": "running", "backend_type": "subprocess", "spawn_mode": "persistent"},
        },
    )

    sent: list[tuple[str, str]] = []

    async def _fake_send(self, arguments, context):
        sent.append((arguments.task_id, arguments.message))
        return ToolResult(output=f"Sent message to agent {arguments.task_id}")

    monkeypatch.setattr("treecode.tools.swarm_handshake_tool.SendMessageTool.execute", _fake_send)

    a_log = tmp_path / "a.log"
    b_log = tmp_path / "b.log"
    a_log.write_text(
        'TCJSON:{"type":"assistant_complete","message":"A ready"}\n[status] agent finished processing prompt (idle, waiting for next message)\n',
        encoding="utf-8",
    )
    b_log.write_text(
        'TCJSON:{"type":"assistant_complete","message":"B ready"}\n[status] agent finished processing prompt (idle, waiting for next message)\n',
        encoding="utf-8",
    )

    def _task(task_id: str):
        path = a_log if task_id == "task-a" else b_log
        return TaskRecord(
            id=task_id,
            type="in_process_teammate",
            status="running",
            description=task_id,
            cwd=str(tmp_path),
            output_file=path,
            command="python -m treecode --backend-only",
        )

    monkeypatch.setattr("treecode.tools.swarm_handshake_tool.load_persisted_task_record", _task)

    tool = SwarmHandshakeTool()
    result = await tool.execute(
        SwarmHandshakeToolInput(wait_seconds=0),
        ToolExecutionContext(
            cwd=tmp_path,
            metadata={
                "session_id": "sess-main",
                "swarm_agent_id": "main@default",
                "swarm_root_agent_id": "main@default",
                "swarm_lineage_path": ("main@default",),
            },
        ),
    )

    assert sent == [
        ("A@default", "你好！我是你的父节点 main@default。请确认你的 agent id、当前状态，以及是否 ready 继续协作。"),
        ("B@default", "你好！我是你的父节点 main@default。请确认你的 agent id、当前状态，以及是否 ready 继续协作。"),
    ]
    assert "A@default" in result.output
    assert "B@default" in result.output
    assert "A ready" in result.output
    assert "B ready" in result.output


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
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
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
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
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
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
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
async def test_agent_tool_supports_explicit_agent_name_distinct_from_type(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))
    fresh_reg = AgentContextRegistry()
    monkeypatch.setattr("treecode.tools.agent_tool.get_context_registry", lambda: fresh_reg)
    captured = {}

    class FakeExecutor:
        type = "subprocess"

        async def spawn(self, config):
            captured["config"] = config
            from treecode.swarm.types import SpawnResult

            return SpawnResult(
                task_id="task-xyz",
                agent_id=f"{config.name}@{config.team}",
                backend_type="subprocess",
            )

    class FakeRegistry:
        def get_executor(self, backend_type=None):
            assert backend_type == "subprocess"
            return FakeExecutor()

    monkeypatch.setattr("treecode.tools.agent_tool.get_backend_registry", lambda: FakeRegistry())

    result = await AgentTool().execute(
        AgentToolInput(
            description="spawn named translator",
            prompt="translate hello",
            subagent_type="general-purpose",
            agent_name="A1",
            spawn_mode="persistent",
        ),
        ToolExecutionContext(cwd=tmp_path),
    )

    assert result.is_error is False
    assert "A1@default" in result.output
    assert captured["config"].name == "A1"


@pytest.mark.asyncio
async def test_agent_tool_propagates_tree_identity_to_spawn_config(tmp_path: Path, monkeypatch):
    fresh_reg = AgentContextRegistry()
    monkeypatch.setattr("treecode.tools.agent_tool.get_context_registry", lambda: fresh_reg)
    captured = {}

    class FakeExecutor:
        type = "subprocess"

        async def spawn(self, config):
            captured["config"] = config
            from treecode.swarm.types import SpawnResult

            return SpawnResult(
                task_id="task-123",
                agent_id=f"{config.name}@{config.team}",
                backend_type="subprocess",
            )

    class FakeRegistry:
        def get_executor(self, backend_type=None):
            assert backend_type == "subprocess"
            return FakeExecutor()

    monkeypatch.setattr("treecode.tools.agent_tool.get_backend_registry", lambda: FakeRegistry())
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
    monkeypatch.setattr("treecode.tools.agent_tool.get_context_registry", lambda: fresh_reg)
    store = get_event_store()
    store.clear()

    class FakeExecutor:
        type = "subprocess"

        async def spawn(self, config):
            from treecode.swarm.types import SpawnResult

            return SpawnResult(
                task_id="task-123",
                agent_id=f"{config.name}@{config.team}",
                backend_type="subprocess",
            )

    class FakeRegistry:
        def get_executor(self, backend_type=None):
            assert backend_type == "subprocess"
            return FakeExecutor()

    monkeypatch.setattr("treecode.tools.agent_tool.get_backend_registry", lambda: FakeRegistry())
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
    monkeypatch.setattr("treecode.tools.agent_tool.get_context_registry", lambda: fresh_reg)
    class FakeExecutor:
        type = "subprocess"

        async def spawn(self, config):
            from treecode.swarm.types import SpawnResult

            return SpawnResult(
                task_id="task-123",
                agent_id=f"{config.name}@{config.team}",
                backend_type="subprocess",
            )

    class FakeRegistry:
        def get_executor(self, backend_type=None):
            assert backend_type == "subprocess"
            return FakeExecutor()

    monkeypatch.setattr("treecode.tools.agent_tool.get_backend_registry", lambda: FakeRegistry())
    monkeypatch.setattr("treecode.tools.agent_tool.get_team_registry", lambda: TeamRegistry())
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
    monkeypatch.setattr("treecode.tools.agent_tool.get_context_registry", lambda: reg)
    store = get_event_store()
    store.clear()

    class FakeExecutor:
        type = "subprocess"

        async def spawn(self, config):
            from treecode.swarm.types import SpawnResult

            return SpawnResult(
                task_id=f"task-{config.name}",
                agent_id=f"{config.name}@{config.team}",
                backend_type="subprocess",
            )

    class FakeRegistry:
        def get_executor(self, backend_type=None):
            return FakeExecutor()

    monkeypatch.setattr("treecode.tools.agent_tool.get_backend_registry", lambda: FakeRegistry())
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
