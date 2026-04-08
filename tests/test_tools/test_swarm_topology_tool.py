"""Tests for the projection-backed swarm_topology tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from openharness.swarm.event_store import EventStore
from openharness.swarm.events import new_swarm_event
from openharness.tools.base import ToolExecutionContext
from openharness.tools.swarm_topology_tool import SwarmTopologyTool, SwarmTopologyToolInput


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
    monkeypatch.setattr("openharness.tools.swarm_topology_tool.get_event_store", _seed_store)
    monkeypatch.setattr("openharness.tools.swarm_topology_tool.live_runtime_state", _runtime_state)

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
    monkeypatch.setattr("openharness.tools.swarm_topology_tool.get_event_store", _seed_store)
    monkeypatch.setattr("openharness.tools.swarm_topology_tool.live_runtime_state", _runtime_state)

    tool = SwarmTopologyTool()
    result = await tool.execute(
        SwarmTopologyToolInput(scope="global", view="live"),
        ToolExecutionContext(cwd=tmp_path),
    )

    assert result.is_error is False
    assert "leader@demo" in result.metadata["tree"]["nodes"]
    assert "worker@demo" in result.metadata["tree"]["nodes"]
    assert "stale@demo" not in result.metadata["tree"]["nodes"]
