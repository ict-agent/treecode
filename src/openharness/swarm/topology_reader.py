"""Helpers for building consistent swarm topology views from the event stream."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from openharness.swarm.events import SwarmEvent
from openharness.swarm.projections import SwarmProjection
from openharness.swarm.registry import get_backend_registry
from openharness.tasks.manager import load_persisted_task_record

TopologyView = Literal["live", "raw_events"]


@dataclass(frozen=True)
class TopologySnapshot:
    """Materialized topology plus the visibility envelope used to build it."""

    tree: dict[str, Any]
    timeline: tuple[SwarmEvent, ...]
    visible_agent_ids: frozenset[str]
    runtime_state: dict[str, dict[str, Any]]

    def subtree(self, agent_id: str) -> dict[str, Any] | None:
        """Return the subtree rooted at ``agent_id`` from the current tree view."""
        return subtree_snapshot(self.tree, agent_id)

    def lookup(self, agent_id: str) -> dict[str, Any] | None:
        """Return parent/children/root/lineage metadata for one visible node."""
        node = self.tree["nodes"].get(agent_id)
        if node is None:
            return None
        lineage = tuple(str(item) for item in node.get("lineage_path", []))
        return {
            "agent_id": agent_id,
            "parent_agent_id": node.get("parent_agent_id"),
            "children": list(node.get("children", [])),
            "lineage_path": list(lineage),
            "root_agent_id": node.get("root_agent_id") or (lineage[0] if lineage else agent_id),
            "status": node.get("status"),
            "node": dict(node),
            "subtree": subtree_snapshot(self.tree, agent_id),
        }


def build_projection(events: tuple[SwarmEvent, ...]) -> SwarmProjection:
    """Replay one event stream into a projection."""
    projection = SwarmProjection()
    for event in events:
        projection.apply(event)
    return projection


def materialize_topology(
    projection: SwarmProjection,
    *,
    view: TopologyView,
    runtime_state_provider: Any | None = None,
) -> TopologySnapshot:
    """Return the selected topology view for an existing projection."""
    tree = projection.tree_snapshot()
    timeline = projection.timeline()
    runtime_state: dict[str, dict[str, Any]] = {}
    if view == "live" and runtime_state_provider is not None:
        runtime_state = dict(runtime_state_provider(timeline))
        tree = filter_tree_by_runtime_state(tree, runtime_state)
    visible_agent_ids = frozenset(str(agent_id) for agent_id in tree["nodes"].keys())
    return TopologySnapshot(
        tree=tree,
        timeline=timeline,
        visible_agent_ids=visible_agent_ids,
        runtime_state=runtime_state,
    )


def live_runtime_state(events: tuple[SwarmEvent, ...]) -> dict[str, dict[str, Any]]:
    """Best-effort runtime liveness derived from backend registries and persisted tasks."""
    latest_spawn: dict[str, SwarmEvent] = {}
    for event in events:
        if event.event_type != "agent_spawned" or bool(event.payload.get("synthetic", False)):
            continue
        latest_spawn[event.agent_id] = event

    registry = get_backend_registry()
    active_in_process: set[str] = set()
    with_context = None
    try:
        with_context = registry.get_executor("in_process")
    except KeyError:
        with_context = None
    if with_context is not None and hasattr(with_context, "active_agents"):
        active_in_process = set(with_context.active_agents())

    runtime_state: dict[str, dict[str, Any]] = {}
    for agent_id, event in latest_spawn.items():
        backend_type = event.payload.get("backend_type")
        spawn_mode = event.payload.get("spawn_mode")
        task_id = event.payload.get("task_id")
        if backend_type == "in_process":
            if agent_id not in active_in_process:
                continue
            runtime_state[agent_id] = {
                "status": "running",
                "backend_type": "in_process",
                "spawn_mode": spawn_mode,
            }
            continue

        if task_id is not None:
            task = load_persisted_task_record(str(task_id))
            if task is None or task.status in {"completed", "failed", "killed"}:
                continue
            runtime_state[agent_id] = {
                "status": "paused" if task.metadata.get("paused") == "true" else "running",
                "backend_type": backend_type or "subprocess",
                "spawn_mode": spawn_mode,
            }

    return runtime_state


def filter_tree_by_runtime_state(
    tree: dict[str, Any],
    runtime_state: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Keep only runtime-active nodes and the ancestors needed to root them."""
    keep = set(runtime_state.keys())
    if not keep:
        return tree
    changed = True
    while changed:
        changed = False
        for agent_id in list(keep):
            parent_agent_id = tree["nodes"].get(agent_id, {}).get("parent_agent_id")
            if parent_agent_id and parent_agent_id in tree["nodes"] and parent_agent_id not in keep:
                keep.add(parent_agent_id)
                changed = True
    filtered_nodes: dict[str, dict[str, Any]] = {}
    for agent_id, node in tree["nodes"].items():
        if agent_id not in keep:
            continue
        updated = dict(node)
        updated["children"] = [child for child in node.get("children", []) if child in keep]
        state = runtime_state.get(agent_id)
        if state is not None:
            updated["status"] = state.get("status", updated.get("status"))
            if updated.get("backend_type") is None:
                updated["backend_type"] = state.get("backend_type")
            if updated.get("spawn_mode") is None:
                updated["spawn_mode"] = state.get("spawn_mode")
        filtered_nodes[agent_id] = updated
    roots = [
        agent_id
        for agent_id in tree["roots"]
        if agent_id in filtered_nodes and filtered_nodes[agent_id].get("parent_agent_id") not in filtered_nodes
    ]
    if not roots:
        roots = [
            agent_id for agent_id, node in filtered_nodes.items() if node.get("parent_agent_id") not in filtered_nodes
        ]
    return {"roots": roots, "nodes": filtered_nodes}


def subtree_snapshot(tree: dict[str, Any], root_agent_id: str) -> dict[str, Any] | None:
    """Extract a rooted subtree from a debugger-style tree snapshot."""
    if root_agent_id not in tree["nodes"]:
        return None
    keep: list[str] = [root_agent_id]
    ordered: list[str] = []
    while keep:
        agent_id = keep.pop(0)
        ordered.append(agent_id)
        keep.extend(
            child for child in tree["nodes"].get(agent_id, {}).get("children", []) if child in tree["nodes"]
        )
    nodes: dict[str, dict[str, Any]] = {}
    for agent_id in ordered:
        node = dict(tree["nodes"][agent_id])
        node["children"] = [child for child in node.get("children", []) if child in tree["nodes"]]
        nodes[agent_id] = node
    return {"roots": [root_agent_id], "nodes": nodes}
