"""Projection-backed swarm topology lookup tool."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from treecode.swarm.event_store import get_event_store
from treecode.swarm.events import SwarmEvent
from treecode.swarm.topology_reader import build_projection, live_runtime_state, materialize_topology
from treecode.tools.base import BaseTool, ToolExecutionContext, ToolResult
from treecode.tools.swarm_context_tool import resolve_swarm_identity


class SwarmTopologyToolInput(BaseModel):
    """Read-only topology query parameters."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = Field(default=None, description="Target agent id. Defaults to the current swarm agent.")
    view: Literal["live", "raw_events"] = Field(
        default="live",
        description="Topology projection to read: current live runtime or full raw event history.",
    )
    scope: Literal["global", "current_session", "agent_subtree", "agent_summary"] = Field(
        default="agent_summary",
        description="Return the full tree, a rooted subtree, or one agent summary.",
    )


class SwarmTopologyTool(BaseTool):
    """Expose the global swarm topology from the event-sourced projection."""

    name = "swarm_topology"
    description = (
        "Read the multi-agent swarm topology from the shared swarm event log. "
        "Returns either the full tree, the current session tree, a subtree, or one agent summary, using the same "
        "projection rules as the debugger. Prefer scope=current_session with view=live for the current agent tree; "
        "use swarm_context for your own identity only. "
        "Use this or swarm_context for current live topology; "
        "do not reconstruct the tree by scanning ~/.treecode/data/swarm/contexts/."
    )
    input_model = SwarmTopologyToolInput

    def is_read_only(self, arguments: SwarmTopologyToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: SwarmTopologyToolInput, context: ToolExecutionContext) -> ToolResult:
        resolved = resolve_swarm_identity(context)
        agent_id = arguments.agent_id
        if agent_id is None and resolved is not None:
            agent_id = resolved[0]
        if arguments.scope != "global" and not agent_id:
            return ToolResult(
                output="agent_id is required for agent_summary or agent_subtree when no swarm teammate metadata is active.",
                is_error=True,
            )
        events = get_event_store().all_events()
        topology = materialize_topology(
            build_projection(events),
            view=arguments.view,
            runtime_state_provider=live_runtime_state if arguments.view == "live" else None,
        )
        if arguments.scope == "current_session":
            if resolved is None:
                return ToolResult(
                    output="current_session scope requires active swarm metadata.",
                    is_error=True,
                )
            current_tree = _current_session_tree(
                events=events,
                base_tree=topology.tree,
                runtime_state=topology.runtime_state,
                current_agent_id=resolved[0],
                current_parent_agent_id=resolved[1],
                current_root_agent_id=resolved[2],
                current_lineage_path=resolved[3],
                current_session_id=str(context.metadata.get("session_id") or resolved[0]),
                view=arguments.view,
            )
            metadata = {
                "view": arguments.view,
                "scope": arguments.scope,
                "tree": current_tree,
            }
            roots = ", ".join(current_tree["roots"]) or "(none)"
            return ToolResult(
                output=f"Swarm topology ({arguments.view}/current_session): {len(current_tree['nodes'])} visible agents across roots {roots}.",
                metadata=metadata,
            )
        metadata = {
            "view": arguments.view,
            "scope": arguments.scope,
            "tree": topology.tree,
        }
        if arguments.scope == "global":
            agent_count = len(topology.tree["nodes"])
            roots = ", ".join(topology.tree["roots"]) or "(none)"
            return ToolResult(
                output=f"Swarm topology ({arguments.view}): {agent_count} visible agents across roots {roots}.",
                metadata=metadata,
            )

        assert agent_id is not None
        agent = topology.lookup(agent_id)
        if agent is None:
            return ToolResult(
                output=f"Agent `{agent_id}` is not visible in the `{arguments.view}` topology view.",
                is_error=True,
                metadata=metadata,
            )

        metadata["agent"] = agent
        if arguments.scope == "agent_subtree":
            subtree = topology.subtree(agent_id)
            metadata["subtree"] = subtree
            subtree_nodes = len(subtree["nodes"]) if subtree is not None else 0
            return ToolResult(
                output=f"Subtree for `{agent_id}` in `{arguments.view}` view contains {subtree_nodes} visible agents.",
                metadata=metadata,
            )

        parent = agent["parent_agent_id"] or "(root)"
        children = ", ".join(agent["children"]) or "(none)"
        lineage = " -> ".join(agent["lineage_path"]) or agent_id
        return ToolResult(
            output=(
                f"Agent `{agent_id}` in `{arguments.view}` view: parent={parent}, "
                f"children={children}, lineage={lineage}."
            ),
            metadata=metadata,
        )


def _current_session_tree(
    *,
    events: tuple[SwarmEvent, ...],
    base_tree: dict[str, Any],
    runtime_state: dict[str, dict[str, Any]],
    current_agent_id: str,
    current_parent_agent_id: str | None,
    current_root_agent_id: str,
    current_lineage_path: tuple[str, ...],
    current_session_id: str,
    view: str,
) -> dict[str, Any]:
    spawn_events: dict[str, SwarmEvent] = {}
    for event in events:
        if event.event_type == "agent_spawned":
            spawn_events[event.agent_id] = event

    active_ids = set(base_tree["nodes"].keys()) if view != "live" else set(runtime_state.keys())
    keep: set[str] = set()
    frontier: set[str] = {current_session_id}
    changed = True
    while changed:
        changed = False
        for agent_id, event in spawn_events.items():
            if agent_id in keep or agent_id not in active_ids:
                continue
            parent_session_id = str(event.payload.get("parent_session_id") or "")
            if parent_session_id and parent_session_id in frontier:
                keep.add(agent_id)
                frontier.add(str(event.session_id or agent_id))
                changed = True

    nodes: dict[str, dict[str, Any]] = {}
    for agent_id in keep:
        node = base_tree["nodes"].get(agent_id)
        if node is None:
            continue
        updated = dict(node)
        updated["children"] = [child for child in node.get("children", []) if child in keep]
        nodes[agent_id] = updated

    current_node = dict(base_tree["nodes"].get(current_agent_id, {}))
    current_node.setdefault("agent_id", current_agent_id)
    current_node.setdefault("name", current_agent_id.split("@", 1)[0])
    current_node.setdefault("team", current_agent_id.split("@", 1)[1] if "@" in current_agent_id else "default")
    current_node["parent_agent_id"] = current_parent_agent_id
    current_node["root_agent_id"] = current_root_agent_id
    current_node["lineage_path"] = list(current_lineage_path)
    current_node["children"] = [
        agent_id
        for agent_id, event in spawn_events.items()
        if agent_id in keep and event.parent_agent_id == current_agent_id
    ]
    nodes[current_agent_id] = current_node

    return {"roots": [current_agent_id], "nodes": nodes}
