"""Tests for swarm topology report formatting (used by ``swarm_context`` tool)."""

from __future__ import annotations

from treecode.prompts.swarm_topology import format_swarm_topology_section, list_known_child_agent_ids
from treecode.swarm.context_registry import AgentContextRegistry, AgentContextSnapshot


def test_format_swarm_topology_section_contains_ids_and_depth():
    text = format_swarm_topology_section(
        agent_id="leaf@default",
        parent_agent_id="mid@default",
        root_agent_id="root@default",
        lineage_path=("root@default", "mid@default", "leaf@default"),
    )
    assert "leaf@default" in text
    assert "mid@default" in text
    assert "root@default" in text
    assert "Depth" in text
    assert "2" in text  # depth from root
    assert "Historical files under `~/.treecode/data/swarm/contexts/` are cache snapshots" in text


def test_list_known_child_agent_ids_and_format_shows_children():
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
    assert list_known_child_agent_ids("parent@default", registry=reg) == ["child@default"]
    text = format_swarm_topology_section(
        agent_id="parent@default",
        parent_agent_id="root@default",
        root_agent_id="root@default",
        lineage_path=("root@default", "parent@default"),
        registry=reg,
    )
    assert "child@default" in text
