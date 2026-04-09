"""Session-scoped swarm identity: tie live topology to one leader session."""

from __future__ import annotations

from openharness.swarm.events import SwarmEvent


def leader_session_by_agent_id(events: tuple[SwarmEvent, ...]) -> dict[str, str]:
    """Map ``agent_id`` → ``leader_session_id`` from the latest ``agent_spawned`` per agent."""

    out: dict[str, str] = {}
    for event in reversed(events):
        if event.event_type != "agent_spawned":
            continue
        if event.agent_id in out:
            continue
        ls = event.payload.get("leader_session_id")
        if isinstance(ls, str) and ls.strip():
            out[event.agent_id] = ls.strip()
    return out


def filter_live_nodes_for_leader_session(
    live_nodes: dict[str, object],
    leader_session_id: str | None,
    events: tuple[SwarmEvent, ...],
) -> dict[str, object]:
    """Drop live nodes that belong to a different leader session (when tagged in events)."""

    if not leader_session_id or not live_nodes:
        return live_nodes
    leader_map = leader_session_by_agent_id(events)
    filtered: dict[str, object] = {}
    for agent_id, node in live_nodes.items():
        recorded = leader_map.get(agent_id)
        if recorded is not None and recorded != leader_session_id:
            continue
        filtered[agent_id] = node
    return filtered


def filter_agent_ids_for_leader_session(
    agent_ids: list[str],
    leader_session_id: str | None,
    events: tuple[SwarmEvent, ...],
) -> list[str]:
    """Keep only agent ids whose latest spawn is for *leader_session_id* (or untagged legacy)."""

    if not leader_session_id:
        return list(agent_ids)
    leader_map = leader_session_by_agent_id(events)
    out: list[str] = []
    for agent_id in agent_ids:
        recorded = leader_map.get(agent_id)
        if recorded is not None and recorded != leader_session_id:
            continue
        out.append(agent_id)
    return out
