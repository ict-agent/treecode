"""Tests for swarm_context tool and resolve_swarm_identity."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    reg.register(
        AgentContextSnapshot(
            agent_id="child@default",
            session_id="s",
            parent_agent_id="parent@default",
            root_agent_id="root@default",
            lineage_path=("root@default", "parent@default", "child@default"),
            prompt="p",
            system_prompt="s",
            messages=(),
        )
    )
    monkeypatch.setattr("openharness.tools.swarm_context_tool.get_context_registry", lambda: reg)
    monkeypatch.setattr("openharness.prompts.swarm_topology.get_context_registry", lambda: reg)

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


@pytest.mark.asyncio
async def test_swarm_context_tool_no_metadata(tmp_path):
    tool = SwarmContextTool()
    ctx = ToolExecutionContext(cwd=tmp_path, metadata={})
    out = await tool.execute(SwarmContextToolInput(), ctx)
    assert "No swarm" in out.output
