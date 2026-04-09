"""Tests for the swarm_gather tool."""

from __future__ import annotations

from pathlib import Path
import shlex

import pytest

from openharness.swarm.event_store import EventStore
from openharness.swarm.events import new_swarm_event
from openharness.swarm.gather import GatherNodeResult, emit_gather_result
from openharness.tools.base import ToolExecutionContext
from openharness.tools.base import ToolResult
from openharness.tools.swarm_gather_tool import SwarmGatherTool, SwarmGatherToolInput


@pytest.mark.asyncio
async def test_swarm_gather_tool_loads_spec_and_invokes_recursive_runner(tmp_path: Path, monkeypatch):
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "gather" / "gather_handshake.md"
    )
    gather_dir = tmp_path / ".openharness" / "gather"
    gather_dir.mkdir(parents=True, exist_ok=True)
    (gather_dir / "gather_handshake.md").write_text(
        fixture_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    async def fake_recursive_runner(**kwargs):
        captured.update(kwargs)
        return GatherNodeResult(
            agent_id="parent@default",
            status="ok",
            self_result={"ready": True},
            children=[],
        )

    async def fake_local_runner(**kwargs):
        captured["local_runner_kwargs"] = kwargs
        return {"ready": True}

    monkeypatch.setattr(
        "openharness.tools.swarm_gather_tool.run_recursive_gather",
        fake_recursive_runner,
    )
    monkeypatch.setattr(
        "openharness.tools.swarm_gather_tool.resolve_live_child_agent_ids",
        lambda context, current_agent_id: ["child-a@default", "child-b@default"],
    )

    tool = SwarmGatherTool()
    result = await tool.execute(
        SwarmGatherToolInput(
            request="collect handshake",
            spec_name="gather_handshake",
        ),
        ToolExecutionContext(
            cwd=tmp_path,
            metadata={
                "session_id": "sess-parent",
                "swarm_agent_id": "parent@default",
                "swarm_parent_agent_id": "main@default",
                "swarm_root_agent_id": "main@default",
                "swarm_lineage_path": ("main@default", "parent@default"),
                "run_gather_local": fake_local_runner,
            },
        ),
    )

    assert result.is_error is False
    assert captured["current_agent_id"] == "parent@default"
    assert captured["child_agent_ids"] == ["child-a@default", "child-b@default"]
    assert captured["spec"].name == "gather_handshake"
    assert result.metadata["result"]["agent_id"] == "parent@default"


@pytest.mark.asyncio
async def test_swarm_gather_tool_executes_gather_handshake_flow_end_to_end(tmp_path: Path, monkeypatch):
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "gather" / "gather_handshake.md"
    )
    gather_dir = tmp_path / ".openharness" / "gather"
    gather_dir.mkdir(parents=True, exist_ok=True)
    (gather_dir / "gather_handshake.md").write_text(
        fixture_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    store = EventStore()

    async def fake_send_message(self, arguments, context):
        del self, context
        tokens = shlex.split(arguments.message)
        gather_id = tokens[tokens.index("--gather-id") + 1]
        emit_gather_result(
            event_store=store,
            gather_id=gather_id,
            agent_id=arguments.task_id,
            root_agent_id="main@default",
            parent_agent_id="parent@default",
            session_id=f"sess-{arguments.task_id}",
            result=GatherNodeResult(
                agent_id=arguments.task_id,
                status="ok",
                self_result={"agent_id": arguments.task_id, "ready": True},
                children=[],
            ),
        )
        return ToolResult(output=f"sent {arguments.task_id}")

    monkeypatch.setattr("openharness.tools.swarm_gather_tool.get_event_store", lambda: store)
    monkeypatch.setattr(
        "openharness.tools.swarm_gather_tool.resolve_live_child_agent_ids",
        lambda context, current_agent_id: ["child-a@default", "child-b@default"],
    )
    monkeypatch.setattr(
        "openharness.tools.swarm_gather_tool.SendMessageTool.execute",
        fake_send_message,
    )

    tool = SwarmGatherTool()
    result = await tool.execute(
        SwarmGatherToolInput(
            request="collect handshake",
            spec_name="gather_handshake",
        ),
        ToolExecutionContext(
            cwd=tmp_path,
            metadata={
                "session_id": "sess-parent",
                "swarm_agent_id": "parent@default",
                "swarm_parent_agent_id": "main@default",
                "swarm_root_agent_id": "main@default",
                "swarm_lineage_path": ("main@default", "parent@default"),
            },
        ),
    )

    assert result.is_error is False
    assert result.metadata["result"]["agent_id"] == "parent@default"
    assert result.metadata["result"]["self_result"]["role"] == "branch"
    assert [child["agent_id"] for child in result.metadata["result"]["children"]] == [
        "child-a@default",
        "child-b@default",
    ]


@pytest.mark.asyncio
async def test_swarm_gather_tool_prefers_summary_text_in_output(tmp_path: Path, monkeypatch):
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "gather" / "gather_handshake.md"
    )
    gather_dir = tmp_path / ".openharness" / "gather"
    gather_dir.mkdir(parents=True, exist_ok=True)
    (gather_dir / "gather_handshake.md").write_text(
        fixture_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    async def fake_recursive_runner(**kwargs):
        del kwargs
        return GatherNodeResult(
            agent_id="parent@default",
            status="ok",
            self_result={"ready": True},
            children=[],
            summary_text="Topology summary for parent",
        )

    monkeypatch.setattr(
        "openharness.tools.swarm_gather_tool.run_recursive_gather",
        fake_recursive_runner,
    )
    monkeypatch.setattr(
        "openharness.tools.swarm_gather_tool.resolve_live_child_agent_ids",
        lambda context, current_agent_id: [],
    )

    tool = SwarmGatherTool()
    result = await tool.execute(
        SwarmGatherToolInput(
            request="collect handshake",
            spec_name="gather_handshake",
        ),
        ToolExecutionContext(
            cwd=tmp_path,
            metadata={
                "session_id": "sess-parent",
                "swarm_agent_id": "parent@default",
                "swarm_parent_agent_id": "main@default",
                "swarm_root_agent_id": "main@default",
                "swarm_lineage_path": ("main@default", "parent@default"),
            },
        ),
    )

    assert "Topology summary for parent" in result.output
    assert "gather_id:" in result.output
    assert "session_id: sess-parent" in result.output
    assert "loaded_spec:" in result.output
    assert "timeout_seconds:" in result.output


@pytest.mark.asyncio
async def test_swarm_gather_tool_resolves_stale_target_to_unique_live_candidate(tmp_path: Path, monkeypatch):
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "gather" / "gather_handshake.md"
    )
    gather_dir = tmp_path / ".openharness" / "gather"
    gather_dir.mkdir(parents=True, exist_ok=True)
    (gather_dir / "gather_handshake.md").write_text(
        fixture_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    store = EventStore()
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="A@default",
            parent_agent_id="main@default",
            root_agent_id="main@default",
            session_id="sess-A",
            payload={
                "name": "A",
                "team": "default",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-A",
                "parent_session_id": "sess-main",
                "lineage_path": ["main@default", "A@default"],
                "leader_session_id": "sess-main",
            },
        )
    )

    sent_to: list[str] = []

    async def fake_send_message(self, arguments, context):
        del self, context
        sent_to.append(arguments.task_id)
        tokens = shlex.split(arguments.message)
        gather_id = tokens[tokens.index("--gather-id") + 1]
        emit_gather_result(
            event_store=store,
            gather_id=gather_id,
            agent_id=arguments.task_id,
            root_agent_id="main@default",
            parent_agent_id="main@default",
            session_id="sess-A14",
            result=GatherNodeResult(
                agent_id=arguments.task_id,
                status="ok",
                self_result={"agent_id": arguments.task_id, "ready": True},
                children=[],
            ),
        )
        return ToolResult(output=f"sent {arguments.task_id}")

    monkeypatch.setattr("openharness.tools.swarm_gather_tool.get_event_store", lambda: store)
    monkeypatch.setattr(
        "openharness.tools.swarm_gather_tool.live_runtime_state",
        lambda _events: {
            "A@default": {"status": "running", "backend_type": "subprocess", "spawn_mode": "persistent"},
        },
    )
    monkeypatch.setattr(
        "openharness.tools.swarm_gather_tool.SendMessageTool.execute",
        fake_send_message,
    )

    tool = SwarmGatherTool()
    result = await tool.execute(
        SwarmGatherToolInput(
            request="collect handshake",
            spec_name="gather_handshake",
            target_agent_id="A@default",
        ),
        ToolExecutionContext(
            cwd=tmp_path,
            metadata={
                "session_id": "sess-main",
                "swarm_leader_session_id": "sess-main",
                "swarm_agent_id": "main@default",
                "swarm_root_agent_id": "main@default",
                "swarm_lineage_path": ("main@default",),
            },
        ),
    )

    assert sent_to == ["A@default"]
    assert result.metadata["result"]["agent_id"] == "A@default"
