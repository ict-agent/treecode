"""Tests for tree-aware swarm runtime graph and projections."""

from __future__ import annotations

from treecode.swarm.event_store import EventStore
from treecode.swarm.events import SwarmEvent, new_swarm_event
from treecode.swarm.projections import SwarmProjection
from treecode.swarm.runtime_graph import AgentNode, RuntimeGraph


def test_runtime_graph_adds_root_and_child_nodes():
    graph = RuntimeGraph()
    root = AgentNode(
        agent_id="leader@demo",
        name="leader",
        team="demo",
        root_agent_id="leader@demo",
        session_id="root-session",
        lineage_path=("leader@demo",),
    )
    child = AgentNode(
        agent_id="worker@demo",
        name="worker",
        team="demo",
        parent_agent_id="leader@demo",
        root_agent_id="leader@demo",
        session_id="child-session",
        lineage_path=("leader@demo", "worker@demo"),
    )

    graph.add_node(root)
    graph.add_node(child)

    assert graph.get_node("leader@demo") == root
    assert graph.get_node("worker@demo") == child
    assert graph.children_of("leader@demo") == ("worker@demo",)
    assert graph.root_nodes() == ("leader@demo",)


def test_runtime_graph_reparents_nodes_and_rewrites_lineage():
    graph = RuntimeGraph()
    graph.add_node(
        AgentNode(
            agent_id="leader@demo",
            name="leader",
            team="demo",
            root_agent_id="leader@demo",
            session_id="root-session",
            lineage_path=("leader@demo",),
        )
    )
    graph.add_node(
        AgentNode(
            agent_id="planner@demo",
            name="planner",
            team="demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="planner-session",
            lineage_path=("leader@demo", "planner@demo"),
        )
    )
    graph.add_node(
        AgentNode(
            agent_id="worker@demo",
            name="worker",
            team="demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            lineage_path=("leader@demo", "worker@demo"),
        )
    )

    graph.reparent("worker@demo", new_parent_agent_id="planner@demo")

    worker = graph.get_node("worker@demo")
    assert worker is not None
    assert worker.parent_agent_id == "planner@demo"
    assert worker.lineage_path == ("leader@demo", "planner@demo", "worker@demo")
    assert graph.children_of("leader@demo") == ("planner@demo",)
    assert graph.children_of("planner@demo") == ("worker@demo",)


def test_runtime_graph_readding_node_removes_stale_parent_link():
    graph = RuntimeGraph()
    graph.add_node(
        AgentNode(
            agent_id="leader@demo",
            name="leader",
            team="demo",
            root_agent_id="leader@demo",
            lineage_path=("leader@demo",),
        )
    )
    graph.add_node(
        AgentNode(
            agent_id="planner@demo",
            name="planner",
            team="demo",
            root_agent_id="leader@demo",
            lineage_path=("leader@demo", "planner@demo"),
        )
    )
    graph.add_node(
        AgentNode(
            agent_id="worker@demo",
            name="worker",
            team="demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            lineage_path=("leader@demo", "worker@demo"),
        )
    )
    graph.add_node(
        AgentNode(
            agent_id="worker@demo",
            name="worker",
            team="demo",
            parent_agent_id="planner@demo",
            root_agent_id="leader@demo",
            lineage_path=("leader@demo", "planner@demo", "worker@demo"),
        )
    )

    assert graph.children_of("leader@demo") == ()
    assert graph.children_of("planner@demo") == ("worker@demo",)


def test_event_store_appends_and_filters_by_agent():
    store = EventStore()
    first = new_swarm_event(
        "agent_spawned",
        agent_id="leader@demo",
        root_agent_id="leader@demo",
        session_id="root-session",
    )
    second = new_swarm_event(
        "turn_started",
        agent_id="worker@demo",
        parent_agent_id="leader@demo",
        root_agent_id="leader@demo",
        session_id="worker-session",
    )

    store.append(first)
    store.append(second)

    assert store.all_events() == (first, second)
    assert store.events_for_agent("worker@demo") == (second,)
    assert store.latest_event("leader@demo") == first


def test_event_store_persists_events_to_disk(tmp_path):
    path = tmp_path / "events.jsonl"
    store = EventStore(storage_path=path)
    event = new_swarm_event(
        "agent_spawned",
        agent_id="worker@demo",
        root_agent_id="worker@demo",
        session_id="worker-session",
    )
    store.append(event)

    reloaded = EventStore(storage_path=path)
    assert reloaded.all_events() == (event,)


def test_event_store_refreshes_from_disk_on_read(tmp_path):
    path = tmp_path / "events.jsonl"
    reader = EventStore(storage_path=path)
    writer = EventStore(storage_path=path)
    event = new_swarm_event(
        "agent_spawned",
        agent_id="worker@demo",
        root_agent_id="worker@demo",
        session_id="worker-session",
    )

    writer.append(event)

    assert reader.all_events() == (event,)


def test_projection_builds_tree_timeline_message_graph_and_approvals():
    projection = SwarmProjection()
    projection.apply(
        new_swarm_event(
            "agent_spawned",
            agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="root-session",
            payload={"name": "leader", "team": "demo"},
        )
    )
    projection.apply(
        new_swarm_event(
            "agent_spawned",
            agent_id="worker@demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            payload={"name": "worker", "team": "demo"},
        )
    )
    projection.apply(
        new_swarm_event(
            "message_delivered",
            agent_id="worker@demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            correlation_id="corr-1",
            payload={"from_agent": "leader@demo", "to_agent": "worker@demo", "text": "do work"},
        )
    )
    projection.apply(
        new_swarm_event(
            "permission_requested",
            agent_id="worker@demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            correlation_id="perm-1",
            payload={"tool_name": "bash", "status": "pending"},
        )
    )

    tree = projection.tree_snapshot()
    assert tree["roots"] == ["leader@demo"]
    assert tree["nodes"]["worker@demo"]["parent_agent_id"] == "leader@demo"

    timeline = projection.timeline()
    assert [event.event_type for event in timeline] == [
        "agent_spawned",
        "agent_spawned",
        "message_delivered",
        "permission_requested",
    ]

    message_edges = projection.message_graph()
    assert message_edges == (
        {
            "from_agent": "leader@demo",
            "to_agent": "worker@demo",
            "correlation_id": "corr-1",
            "event_type": "message_delivered",
            "text": "do work",
        },
    )

    approval_queue = projection.approval_queue()
    assert approval_queue == (
        {
            "agent_id": "worker@demo",
            "correlation_id": "perm-1",
            "tool_name": "bash",
            "status": "pending",
        },
    )


def test_projection_tool_recent_records_called_and_completed():
    projection = SwarmProjection()
    projection.apply(
        new_swarm_event(
            "tool_called",
            agent_id="worker@demo",
            root_agent_id="leader@demo",
            parent_agent_id="leader@demo",
            session_id="worker-session",
            payload={"tool_name": "brief", "tool_input": {"text": "hello"}, "source": "console"},
        )
    )
    projection.apply(
        new_swarm_event(
            "tool_completed",
            agent_id="worker@demo",
            root_agent_id="leader@demo",
            parent_agent_id="leader@demo",
            session_id="worker-session",
            payload={"tool_name": "brief", "is_error": False, "output": "hello world", "source": "console"},
        )
    )
    rows = projection.tool_recent()
    assert len(rows) == 2
    assert rows[0]["phase"] == "called"
    assert rows[0]["tool_name"] == "brief"
    assert rows[0]["tool_input_preview"] == {"text": "hello"}
    assert rows[1]["phase"] == "completed"
    assert rows[1]["output_preview"] == "hello world"
    assert rows[1]["is_error"] is False


def test_projection_includes_manual_message_injected_in_message_graph():
    projection = SwarmProjection()
    projection.apply(
        new_swarm_event(
            "manual_message_injected",
            agent_id="worker@demo",
            root_agent_id="leader@demo",
            parent_agent_id="leader@demo",
            session_id="worker-session",
            payload={"message": "injected text", "source": "debugger"},
        )
    )
    edges = projection.message_graph()
    assert len(edges) == 1
    assert edges[0]["from_agent"] == "debugger"
    assert edges[0]["to_agent"] == "worker@demo"
    assert edges[0]["event_type"] == "manual_message_injected"
    assert edges[0]["text"] == "injected text"


def test_projection_tolerates_status_event_before_spawn():
    projection = SwarmProjection()
    projection.apply(
        new_swarm_event(
            "agent_became_running",
            agent_id="agent@default",
            root_agent_id="agent@default",
            session_id="agent-session",
        )
    )

    snapshot = projection.tree_snapshot()
    assert snapshot["nodes"]["agent@default"]["status"] == "running"
    assert snapshot["nodes"]["agent@default"]["name"] == "agent"


def test_projection_preserves_running_status_when_spawn_arrives_later():
    projection = SwarmProjection()
    projection.apply(
        new_swarm_event(
            "agent_became_running",
            agent_id="agent@default",
            root_agent_id="agent@default",
            session_id="agent-session",
        )
    )
    projection.apply(
        new_swarm_event(
            "agent_spawned",
            agent_id="agent@default",
            root_agent_id="agent@default",
            session_id="agent-session",
            payload={"name": "agent", "team": "default"},
        )
    )

    snapshot = projection.tree_snapshot()
    assert snapshot["nodes"]["agent@default"]["status"] == "running"


def test_swarm_event_round_trip_dict():
    event = new_swarm_event(
        "agent_spawned",
        agent_id="worker@demo",
        parent_agent_id="leader@demo",
        root_agent_id="leader@demo",
        session_id="worker-session",
        correlation_id="corr-1",
        payload={"name": "worker", "team": "demo"},
    )

    loaded = SwarmEvent.from_dict(event.to_dict())

    assert loaded == event
