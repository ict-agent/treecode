"""Human-readable swarm tree reports (e.g. for the ``swarm_context`` tool)."""

from __future__ import annotations

from openharness.swarm.context_registry import AgentContextRegistry, get_context_registry


def list_known_child_agent_ids(
    agent_id: str,
    registry: AgentContextRegistry | None = None,
) -> list[str]:
    """Return other agents registered as direct children of *agent_id* (best-effort)."""
    reg = registry if registry is not None else get_context_registry()
    return sorted(
        aid for aid, snap in reg.snapshots().items() if snap.parent_agent_id == agent_id
    )


def format_swarm_topology_section(
    *,
    agent_id: str,
    parent_agent_id: str | None,
    root_agent_id: str,
    lineage_path: tuple[str, ...],
    children_agent_ids: list[str] | None = None,
    source_label: str = "live registry",
    registry: AgentContextRegistry | None = None,
) -> str:
    """Format a tree snapshot for tool output from projection data or registry fallback."""
    depth = max(0, len(lineage_path) - 1) if lineage_path else 0
    chain = " → ".join(lineage_path) if lineage_path else agent_id
    parent_line = (
        f"`{parent_agent_id}`" if parent_agent_id else "*(none — you are the root of this subtree)*"
    )
    children = (
        children_agent_ids
        if children_agent_ids is not None
        else list_known_child_agent_ids(agent_id, registry=registry)
    )
    children_line = (
        ", ".join(f"`{c}`" for c in children) if children else "*(none registered yet)*"
    )
    return f"""## Swarm position ({source_label})

- **Your agent id**: `{agent_id}`
- **Root of this tree**: `{root_agent_id}`
- **Your direct parent**: {parent_line}
- **Lineage from root to you**: {chain}
- **Depth from root** (0 = root): {depth}
- **Known direct children**: {children_line}

Siblings share the same parent; agents outside the current view may be omitted."""

