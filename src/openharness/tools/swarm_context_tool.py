"""Runtime swarm topology discovery (no static prompt injection)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from openharness.prompts.swarm_topology import format_swarm_topology_section
from openharness.swarm.context_registry import get_context_registry
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


def resolve_swarm_identity(
    context: ToolExecutionContext,
) -> tuple[str, str | None, str, tuple[str, ...]] | None:
    """Resolve current agent id, parent, root, and lineage from task context + metadata + registry.

    Order: in-process :class:`~openharness.swarm.in_process.TeammateContext` (live),
    then :attr:`ToolExecutionContext.metadata` (subprocess / leader sessions),
    then :class:`~openharness.swarm.context_registry.AgentContextSnapshot` for the same id.
    """
    from openharness.swarm.in_process import get_teammate_context

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
        "and known direct children from the live registry. Call this when you need to know where "
        "you are in the tree or who your neighbors are; topology is not repeated in the system prompt."
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
        text = format_swarm_topology_section(
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            root_agent_id=root_agent_id,
            lineage_path=lineage_path,
            registry=get_context_registry(),
        )
        return ToolResult(output=text, metadata={"agent_id": agent_id})
