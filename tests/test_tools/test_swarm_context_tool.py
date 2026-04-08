"""Tests for swarm_context tool and resolve_swarm_identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from openharness.swarm.event_store import EventStore
from openharness.swarm.events import new_swarm_event
from openharness.swarm.context_registry import AgentContextRegistry, AgentContextSnapshot
from openharness.tools.base import ToolExecutionContext
from openharness.tools.swarm_context_tool import SwarmContextTool, SwarmContextToolInput, resolve_swarm_identity


def test_resolve_swarm_identity_from_metadata():
    ctx = ToolExecutionContext(
        cwd=Path("/tmp"),
        metadata={
            "swarm_agent_id": "worker@default",
            "swarm_parent_agent_id": "leader@default",
            "swarm_root_agent_id": "leader@default",
            "swarm_lineage_path": ("leader@default", "worker@default"),
        },
    )
    r = resolve_swarm_identity(ctx)
    assert r is not None
    agent_id, parent, root, lineage = r
    assert agent_id == "worker@default"
    assert parent == "leader@default"
    assert root == "leader@default"
    assert lineage == ("leader@default", "worker@default")


@pytest.mark.asyncio
async def test_swarm_context_tool_outputs_report(tmp_path, monkeypatch):
    reg = AgentContextRegistry()
    store = EventStore()
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="root@default",
            root_agent_id="root@default",
            session_id="root-session",
            payload={
                "name": "root",
                "team": "default",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-root",
                "lineage_path": ["root@default"],
            },
        )
    )
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="parent@default",
            parent_agent_id="root@default",
            root_agent_id="root@default",
            session_id="parent-session",
            payload={
                "name": "parent",
                "team": "default",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-parent",
                "lineage_path": ["root@default", "parent@default"],
            },
        )
    )
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="child@default",
            parent_agent_id="parent@default",
            root_agent_id="root@default",
            session_id="child-session",
            payload={
                "name": "child",
                "team": "default",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-child",
                "lineage_path": ["root@default", "parent@default", "child@default"],
            },
        )
    )
    monkeypatch.setattr("openharness.tools.swarm_context_tool.get_context_registry", lambda: reg)
    monkeypatch.setattr("openharness.tools.swarm_context_tool.get_event_store", lambda: store)
    monkeypatch.setattr(
        "openharness.tools.swarm_context_tool.live_runtime_state",
        lambda events: {
            "root@default": {"status": "running"},
            "parent@default": {"status": "running"},
            "child@default": {"status": "running"},
        },
    )

    ctx = ToolExecutionContext(
        cwd=tmp_path,
        metadata={
            "swarm_agent_id": "parent@default",
            "swarm_root_agent_id": "root@default",
            "swarm_lineage_path": ("root@default", "parent@default"),
        },
    )
    tool = SwarmContextTool()
    out = await tool.execute(SwarmContextToolInput(), ctx)

    assert "parent@default" in out.output
    assert "child@default" in out.output
    assert "Swarm position" in out.output
    assert out.metadata["children"] == ["child@default"]


@pytest.mark.asyncio
async def test_swarm_context_tool_no_metadata(tmp_path):
    tool = SwarmContextTool()
    ctx = ToolExecutionContext(cwd=tmp_path, metadata={})
    out = await tool.execute(SwarmContextToolInput(), ctx)
    assert "No swarm" in out.output
