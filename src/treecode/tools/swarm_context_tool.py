"""Runtime swarm topology discovery (no static prompt injection)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from treecode.prompts.swarm_topology import format_swarm_topology_section
from treecode.swarm.context_registry import get_context_registry
from treecode.swarm.event_store import get_event_store
from treecode.swarm.events import SwarmEvent
from treecode.swarm.topology_reader import build_projection, live_runtime_state, materialize_topology
from treecode.tools.base import BaseTool, ToolExecutionContext, ToolResult


def resolve_swarm_identity(
    context: ToolExecutionContext,
) -> tuple[str, str | None, str, tuple[str, ...]] | None:
    """Resolve current agent id, parent, root, and lineage from task context + metadata + registry.

    Order: in-process :class:`~treecode.swarm.in_process.TeammateContext` (live),
    then :attr:`ToolExecutionContext.metadata` (subprocess / leader sessions),
    then :class:`~treecode.swarm.context_registry.AgentContextSnapshot` for the same id.
    """
    from treecode.swarm.in_process import get_teammate_context

    md = context.metadata or {}
    tc = get_teammate_context()
    reg = get_context_registry()

    agent_id: str | None = None
    parent: str | None = None
    root: str | None = None
    lineage: tuple[str, ...] = ()

    if tc is not None:
        agent_id = tc.agent_id
        parent = tc.parent_agent_id
        root = tc.root_agent_id or agent_id
        lineage = tc.lineage_path if tc.lineage_path else (agent_id,)
    else:
        aid = md.get("swarm_agent_id")
        if not aid:
            return None
        agent_id = str(aid)
        p = md.get("swarm_parent_agent_id")
        parent = str(p) if p else None
        r = md.get("swarm_root_agent_id")
        root = str(r) if r else agent_id
        lp = md.get("swarm_lineage_path")
        if isinstance(lp, (list, tuple)):
            lineage = tuple(str(x) for x in lp)

    snap = reg.get(agent_id) if agent_id else None
    if snap is not None:
        if not lineage:
            lineage = snap.lineage_path
        if parent is None:
            parent = snap.parent_agent_id
        if root is None:
            root = snap.root_agent_id or agent_id
    if not lineage and agent_id:
        lineage = (agent_id,)
    if agent_id is None:
        return None
    if root is None:
        root = agent_id
    return agent_id, parent, root, lineage


class SwarmContextToolInput(BaseModel):
    """No parameters; call to refresh topology from the live registry."""

    model_config = ConfigDict(extra="forbid")


class SwarmContextTool(BaseTool):
    """Expose current swarm tree position on demand (dynamic, not baked into the system prompt)."""

    name = "swarm_context"
    description = (
        "Return your current position in the multi-agent swarm: agent id, parent, root, lineage, "
        "and known direct children from the shared swarm topology projection. Call this when you "
        "need to know where you are in the tree or who your neighbors are. Use swarm_topology(scope=current_session, view=live) "
        "when you need the full current tree. Topology is not repeated in the system prompt. This is the source of truth for the current live tree; do not infer "
        "current topology by scanning ~/.treecode/data/swarm/contexts/ or historical task logs."
    )
    input_model = SwarmContextToolInput

    def is_read_only(self, arguments: SwarmContextToolInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: SwarmContextToolInput, context: ToolExecutionContext) -> ToolResult:
        del arguments
        resolved = resolve_swarm_identity(context)
        if resolved is None:
            return ToolResult(
                output=(
                    "No swarm / multi-agent context is active for this session "
                    "(not running as a teammate with swarm metadata). "
                    "This tool only applies when spawned in a swarm or when swarm ids are set on the runtime."
                ),
                is_error=False,
            )
        agent_id, parent_agent_id, root_agent_id, lineage_path = resolved
        children: list[str] | None = None
        source_label = "fallback metadata (agent not visible in live projection)"
        topology = materialize_topology(
            build_projection(get_event_store().all_events()),
            view="live",
            runtime_state_provider=live_runtime_state,
        )
        summary = topology.lookup(agent_id)
        if summary is not None:
            parent_agent_id = summary["parent_agent_id"]
            root_agent_id = summary["root_agent_id"]
            lineage_path = tuple(str(item) for item in summary["lineage_path"])
            children = list(summary["children"])
            source_label = "event projection / live view"
        elif agent_id == "main@default":
            current_tree = _current_session_tree(
                events=get_event_store().all_events(),
                base_tree=topology.tree,
                runtime_state=topology.runtime_state,
                current_agent_id=agent_id,
                current_parent_agent_id=parent_agent_id,
                current_root_agent_id=root_agent_id,
                current_lineage_path=lineage_path,
                current_session_id=str(context.metadata.get("session_id") or agent_id),
            )
            current_main = current_tree["nodes"].get(agent_id, {})
            children = list(current_main.get("children", []))
            source_label = "current session subtree / live view"
        text = format_swarm_topology_section(
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            root_agent_id=root_agent_id,
            lineage_path=lineage_path,
            children_agent_ids=children,
            source_label=source_label,
            registry=get_context_registry(),
        )
        return ToolResult(output=text, metadata={"agent_id": agent_id, "view": "live", "children": children or []})


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
) -> dict[str, Any]:
    spawn_events: dict[str, SwarmEvent] = {}
    for event in events:
        if event.event_type == "agent_spawned":
            spawn_events[event.agent_id] = event

    keep: set[str] = set()
    frontier: set[str] = {current_session_id}
    active_ids = set(runtime_state.keys())
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
    return {"roots": [current_agent_id], "nodes": {current_agent_id: current_node}}
