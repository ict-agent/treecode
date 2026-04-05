"""Tests for deterministic swarm agent manager scenarios."""

from __future__ import annotations

from openharness.swarm.context_registry import AgentContextRegistry
from openharness.swarm.debugger import SwarmDebuggerService
from openharness.swarm.event_store import EventStore
from openharness.swarm.manager import AgentManager


def test_agent_manager_runs_two_level_fanout_scenario():
    store = EventStore()
    contexts = AgentContextRegistry()
    manager = AgentManager(event_store=store, context_registry=contexts)

    result = manager.run_scenario("two_level_fanout")

    assert result["scenario"] == "two_level_fanout"
    assert result["root_agent_id"] == "main"

    service = SwarmDebuggerService(event_store=store, context_registry=contexts)
    snapshot = service.snapshot()
    nodes = snapshot["tree"]["nodes"]
    assert snapshot["tree"]["roots"] == ["main"]
    assert nodes["main"]["children"] == ["sub1"]
    assert nodes["sub1"]["children"] == ["A", "B"]
    assert nodes["A"]["parent_agent_id"] == "sub1"
    assert nodes["B"]["parent_agent_id"] == "sub1"
    assert nodes["A"]["root_agent_id"] == "main"
    assert nodes["B"]["root_agent_id"] == "main"

    edges = {(edge["from_agent"], edge["to_agent"]) for edge in snapshot["message_graph"]}
    assert ("sub1", "A") in edges
    assert ("sub1", "B") in edges
    assert contexts.get("A") is not None
    assert contexts.get("B") is not None


def test_agent_manager_lists_builtin_scenarios():
    manager = AgentManager(event_store=EventStore(), context_registry=AgentContextRegistry())
    names = manager.list_scenarios()

    assert "two_level_fanout" in names
