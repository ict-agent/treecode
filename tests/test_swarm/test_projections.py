"""Tests for swarm projection materialization."""

from __future__ import annotations

from treecode.swarm.events import new_swarm_event
from treecode.swarm.projections import SwarmProjection


def test_projection_maps_assistant_message_to_message_graph():
    proj = SwarmProjection()
    proj.apply(
        new_swarm_event(
            "assistant_message",
            agent_id="worker@default",
            root_agent_id="leader@default",
            parent_agent_id="leader@default",
            session_id="s1",
            correlation_id="corr-1",
            payload={"text": "Hello from the model", "has_tool_uses": False},
        )
    )
    edges = proj.message_graph()
    assert len(edges) == 1
    assert edges[0]["from_agent"] == "worker@default"
    assert edges[0]["to_agent"] == "user"
    assert edges[0]["event_type"] == "assistant_message"
    assert edges[0]["text"] == "Hello from the model"


def test_projection_tree_snapshot_includes_agent_backend_metadata():
    proj = SwarmProjection()
    proj.apply(
        new_swarm_event(
            "agent_spawned",
            agent_id="worker@default",
            root_agent_id="leader@default",
            parent_agent_id="leader@default",
            session_id="s1",
            payload={
                "name": "worker",
                "team": "default",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "synthetic": False,
            },
        )
    )

    node = proj.tree_snapshot()["nodes"]["worker@default"]
    assert node["backend_type"] == "subprocess"
    assert node["spawn_mode"] == "persistent"
    assert node["synthetic"] is False
