"""Tree-aware runtime graph for spawned swarm agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class AgentNode:
    """Snapshot of one agent inside the runtime tree."""

    agent_id: str
    name: str
    team: str
    parent_agent_id: str | None = None
    root_agent_id: str | None = None
    session_id: str | None = None
    lineage_path: tuple[str, ...] = ()
    status: str = "starting"
    cwd: str | None = None
    worktree_path: str | None = None


class RuntimeGraph:
    """Mutable tree of running agents keyed by ``agent_id``."""

    def __init__(self) -> None:
        self._nodes: dict[str, AgentNode] = {}
        self._children: dict[str | None, list[str]] = {None: []}

    def add_node(self, node: AgentNode) -> None:
        """Insert or replace a node while maintaining the parent/child index."""
        previous = self._nodes.get(node.agent_id)
        if previous is not None and previous.parent_agent_id in self._children:
            stale_children = self._children[previous.parent_agent_id]
            if node.agent_id in stale_children:
                stale_children.remove(node.agent_id)
        self._nodes[node.agent_id] = node
        self._children.setdefault(node.agent_id, [])
        self._children.setdefault(node.parent_agent_id, [])
        if node.agent_id not in self._children[node.parent_agent_id]:
            self._children[node.parent_agent_id].append(node.agent_id)

    def get_node(self, agent_id: str) -> AgentNode | None:
        """Return one node by ID."""
        return self._nodes.get(agent_id)

    def children_of(self, agent_id: str) -> tuple[str, ...]:
        """Return direct child IDs in insertion order."""
        return tuple(self._children.get(agent_id, []))

    def root_nodes(self) -> tuple[str, ...]:
        """Return all root nodes."""
        return tuple(self._children.get(None, []))

    def update_status(self, agent_id: str, status: str) -> None:
        """Update one node's coarse runtime status."""
        node = self._require(agent_id)
        self._nodes[agent_id] = replace(node, status=status)

    def reparent(self, agent_id: str, *, new_parent_agent_id: str | None) -> None:
        """Move a node to a new parent and rewrite lineage for its subtree."""
        node = self._require(agent_id)
        if node.parent_agent_id in self._children:
            with_value = self._children[node.parent_agent_id]
            if agent_id in with_value:
                with_value.remove(agent_id)

        self._children.setdefault(new_parent_agent_id, [])
        if agent_id not in self._children[new_parent_agent_id]:
            self._children[new_parent_agent_id].append(agent_id)

        parent = self._nodes.get(new_parent_agent_id) if new_parent_agent_id else None
        root_agent_id = parent.root_agent_id if parent and parent.root_agent_id else (
            new_parent_agent_id or node.root_agent_id or agent_id
        )
        if parent and parent.lineage_path:
            lineage_path = parent.lineage_path + (agent_id,)
        elif new_parent_agent_id:
            lineage_path = (new_parent_agent_id, agent_id)
        else:
            lineage_path = (agent_id,)

        self._nodes[agent_id] = replace(
            node,
            parent_agent_id=new_parent_agent_id,
            root_agent_id=root_agent_id,
            lineage_path=lineage_path,
        )
        self._rewrite_descendant_lineage(agent_id)

    def snapshot(self) -> dict[str, object]:
        """Return a debugger-friendly tree snapshot."""
        return {
            "roots": list(self.root_nodes()),
            "nodes": {
                agent_id: {
                    **asdict(node),
                    "children": list(self.children_of(agent_id)),
                }
                for agent_id, node in self._nodes.items()
            },
        }

    def _rewrite_descendant_lineage(self, agent_id: str) -> None:
        parent = self._require(agent_id)
        for child_id in self.children_of(agent_id):
            child = self._require(child_id)
            self._nodes[child_id] = replace(
                child,
                root_agent_id=parent.root_agent_id or parent.agent_id,
                lineage_path=parent.lineage_path + (child_id,),
            )
            self._rewrite_descendant_lineage(child_id)

    def _require(self, agent_id: str) -> AgentNode:
        node = self._nodes.get(agent_id)
        if node is None:
            raise KeyError(f"Unknown agent_id: {agent_id}")
        return node
