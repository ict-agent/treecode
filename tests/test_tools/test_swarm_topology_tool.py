"""Tests for the projection-backed swarm_topology tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from treecode.swarm.event_store import EventStore
from treecode.swarm.events import new_swarm_event
from treecode.tools.base import ToolExecutionContext
from treecode.tools.swarm_topology_tool import SwarmTopologyTool, SwarmTopologyToolInput


def _seed_store() -> EventStore:
    store = EventStore()
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="leader-session",
            payload={
                "name": "leader",
                "team": "demo",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-leader",
                "lineage_path": ["leader@demo"],
            },
        )
    )
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="worker@demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            payload={
                "name": "worker",
                "team": "demo",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-worker",
                "lineage_path": ["leader@demo", "worker@demo"],
            },
        )
    )
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="stale@demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="stale-session",
            payload={
                "name": "stale",
                "team": "demo",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-stale",
                "lineage_path": ["leader@demo", "stale@demo"],
            },
        )
    )
    return store


def _runtime_state(_events):
    return {
        "leader@demo": {"status": "running", "backend_type": "subprocess", "spawn_mode": "persistent"},
        "worker@demo": {"status": "running", "backend_type": "subprocess", "spawn_mode": "persistent"},
    }


@pytest.mark.asyncio
async def test_swarm_topology_tool_reports_agent_summary(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("treecode.tools.swarm_topology_tool.get_event_store", _seed_store)
    monkeypatch.setattr("treecode.tools.swarm_topology_tool.live_runtime_state", _runtime_state)

    tool = SwarmTopologyTool()
    result = await tool.execute(
        SwarmTopologyToolInput(agent_id="worker@demo", scope="agent_summary", view="raw_events"),
        ToolExecutionContext(cwd=tmp_path),
    )

    assert result.is_error is False
    assert result.metadata["view"] == "raw_events"
    assert result.metadata["agent"]["parent_agent_id"] == "leader@demo"
    assert result.metadata["agent"]["children"] == []
    assert result.metadata["agent"]["root_agent_id"] == "leader@demo"
    assert "worker@demo" in result.output


@pytest.mark.asyncio
async def test_swarm_topology_tool_live_view_filters_stale_agents(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("treecode.tools.swarm_topology_tool.get_event_store", _seed_store)
    monkeypatch.setattr("treecode.tools.swarm_topology_tool.live_runtime_state", _runtime_state)

    tool = SwarmTopologyTool()
    result = await tool.execute(
        SwarmTopologyToolInput(scope="global", view="live"),
        ToolExecutionContext(cwd=tmp_path),
    )

    assert result.is_error is False
    assert "leader@demo" in result.metadata["tree"]["nodes"]
    assert "worker@demo" in result.metadata["tree"]["nodes"]
    assert "stale@demo" not in result.metadata["tree"]["nodes"]




@pytest.mark.asyncio
async def test_swarm_topology_tool_current_session_scope_filters_to_current_main_children(monkeypatch, tmp_path: Path):
    store = EventStore()
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="A-old@default",
            parent_agent_id="main@default",
            root_agent_id="main@default",
            session_id="A-old@default",
            payload={
                "name": "A-old",
                "team": "default",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-old",
                "parent_session_id": "old-main-session",
                "lineage_path": ["main@default", "A-old@default"],
            },
        )
    )
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="A-new@default",
            parent_agent_id="main@default",
            root_agent_id="main@default",
            session_id="A-new@default",
            payload={
                "name": "A-new",
                "team": "default",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-new",
                "parent_session_id": "sess-main",
                "lineage_path": ["main@default", "A-new@default"],
            },
        )
    )
    monkeypatch.setattr("treecode.tools.swarm_topology_tool.get_event_store", lambda: store)
    monkeypatch.setattr(
        "treecode.tools.swarm_topology_tool.live_runtime_state",
        lambda _events: {
            "A-old@default": {"status": "running", "backend_type": "subprocess", "spawn_mode": "persistent"},
            "A-new@default": {"status": "running", "backend_type": "subprocess", "spawn_mode": "persistent"},
        },
    )

    tool = SwarmTopologyTool()
    result = await tool.execute(
        SwarmTopologyToolInput(scope="current_session", view="live"),
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

    assert result.is_error is False
    assert "main@default" in result.metadata["tree"]["nodes"]
    assert "A-new@default" in result.metadata["tree"]["nodes"]
    assert "A-old@default" not in result.metadata["tree"]["nodes"]
