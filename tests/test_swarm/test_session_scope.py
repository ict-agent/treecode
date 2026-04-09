"""Tests for leader-session-scoped live topology filtering."""

from openharness.swarm.events import new_swarm_event
from openharness.swarm.session_scope import (
    filter_agent_ids_for_leader_session,
    filter_live_nodes_for_leader_session,
    leader_session_by_agent_id,
)


def test_leader_session_by_agent_id_latest_wins():
    events = (
        new_swarm_event(
            "agent_spawned",
            agent_id="A@default",
            root_agent_id="main@default",
            parent_agent_id="main@default",
            session_id="s",
            payload={"leader_session_id": "old"},
        ),
        new_swarm_event(
            "agent_spawned",
            agent_id="A@default",
            root_agent_id="main@default",
            parent_agent_id="main@default",
            session_id="s",
            payload={"leader_session_id": "new"},
        ),
    )
    m = leader_session_by_agent_id(events)
    assert m["A@default"] == "new"


def test_filter_live_nodes_drops_other_leader():
    live_nodes = {"A@default": {}, "B@default": {}}
    events = (
        new_swarm_event(
            "agent_spawned",
            agent_id="A@default",
            root_agent_id="main@default",
            parent_agent_id="main@default",
            session_id="s",
            payload={"leader_session_id": "sess-1"},
        ),
        new_swarm_event(
            "agent_spawned",
            agent_id="B@default",
            root_agent_id="main@default",
            parent_agent_id="main@default",
            session_id="s",
            payload={"leader_session_id": "sess-2"},
        ),
    )
    filtered = filter_live_nodes_for_leader_session(live_nodes, "sess-1", events)
    assert set(filtered.keys()) == {"A@default"}


def test_filter_agent_ids_for_leader_session():
    events = (
        new_swarm_event(
            "agent_spawned",
            agent_id="X@default",
            root_agent_id="main@default",
            parent_agent_id="main@default",
            session_id="s",
            payload={"leader_session_id": "L"},
        ),
        new_swarm_event(
            "agent_spawned",
            agent_id="Y@default",
            root_agent_id="main@default",
            parent_agent_id="main@default",
            session_id="s",
            payload={"leader_session_id": "other"},
        ),
    )
    out = filter_agent_ids_for_leader_session(["X@default", "Y@default"], "L", events)
    assert out == ["X@default"]
