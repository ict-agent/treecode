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


@pytest.mark.asyncio
async def test_swarm_context_main_fallback_does_not_leak_historical_children(tmp_path, monkeypatch):
    reg = AgentContextRegistry()
    reg.register(
        AgentContextSnapshot(
            agent_id="A-old@default",
            session_id="A-old@default",
            parent_agent_id="main@default",
            root_agent_id="main@default",
            lineage_path=("main@default", "A-old@default"),
            prompt="old child",
        )
    )
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
    monkeypatch.setattr("openharness.tools.swarm_context_tool.get_context_registry", lambda: reg)
    monkeypatch.setattr("openharness.tools.swarm_context_tool.get_event_store", lambda: store)
    monkeypatch.setattr(
        "openharness.tools.swarm_context_tool.live_runtime_state",
        lambda _events: {
            "A-old@default": {"status": "running", "backend_type": "subprocess", "spawn_mode": "persistent"},
            "A-new@default": {"status": "running", "backend_type": "subprocess", "spawn_mode": "persistent"},
        },
    )

    tool = SwarmContextTool()
    out = await tool.execute(
        SwarmContextToolInput(),
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

    assert "A-new@default" in out.output
    assert "A-old@default" not in out.output
    assert "**Current live direct children in this session**" in out.output
