"""Projection-backed swarm topology lookup tool."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from openharness.swarm.event_store import get_event_store
from openharness.swarm.topology_reader import build_projection, live_runtime_state, materialize_topology
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.tools.swarm_context_tool import resolve_swarm_identity


class SwarmTopologyToolInput(BaseModel):
    """Read-only topology query parameters."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str | None = Field(default=None, description="Target agent id. Defaults to the current swarm agent.")
    view: Literal["live", "raw_events"] = Field(
        default="live",
        description="Topology projection to read: current live runtime or full raw event history.",
    )
    scope: Literal["global", "agent_subtree", "agent_summary"] = Field(
        default="agent_summary",
        description="Return the full tree, a rooted subtree, or one agent summary.",
    )


class SwarmTopologyTool(BaseTool):
    """Expose the global swarm topology from the event-sourced projection."""

    name = "swarm_topology"
    description = (
        "Read the multi-agent swarm topology from the shared swarm event log. "
        "Returns either the full tree, a subtree, or one agent summary, using the same "
        "projection rules as the debugger."
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

        topology = materialize_topology(
            build_projection(get_event_store().all_events()),
            view=arguments.view,
            runtime_state_provider=live_runtime_state if arguments.view == "live" else None,
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
