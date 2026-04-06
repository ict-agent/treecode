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
    registry: AgentContextRegistry | None = None,
) -> str:
    """Format a tree snapshot for tool output (registry children are resolved at call time)."""
    depth = max(0, len(lineage_path) - 1) if lineage_path else 0
    chain = " → ".join(lineage_path) if lineage_path else agent_id
    parent_line = (
        f"`{parent_agent_id}`" if parent_agent_id else "*(none — you are the root of this subtree)*"
    )
    children = list_known_child_agent_ids(agent_id, registry=registry)
    children_line = (
        ", ".join(f"`{c}`" for c in children) if children else "*(none registered yet)*"
    )
    return f"""## Swarm position (live registry)

- **Your agent id**: `{agent_id}`
- **Root of this tree**: `{root_agent_id}`
- **Your direct parent**: {parent_line}
- **Lineage from root to you**: {chain}
- **Depth from root** (0 = root): {depth}
- **Known direct children** (runtime registry at call time): {children_line}

Siblings share the same parent; not all siblings may appear in the registry."""

