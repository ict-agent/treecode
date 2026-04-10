"""Deterministic multi-agent scenario manager for debugger and tests."""

from __future__ import annotations

from typing import Callable

from treecode.swarm.context_registry import AgentContextRegistry, AgentContextSnapshot
from treecode.swarm.event_store import EventStore
from treecode.swarm.events import new_swarm_event


class AgentManager:
    """Create synthetic agent trees without relying on model behavior."""

    def __init__(self, *, event_store: EventStore, context_registry: AgentContextRegistry) -> None:
        self._event_store = event_store
        self._context_registry = context_registry
        self._scenarios: dict[str, Callable[[], dict[str, object]]] = {
            "single_child": self._single_child,
            "two_level_fanout": self._two_level_fanout,
            "approval_on_leaf": self._approval_on_leaf,
        }

    def list_scenarios(self) -> tuple[str, ...]:
        """Return the available built-in scenario names."""
        return tuple(sorted(self._scenarios))

    def run_scenario(self, name: str) -> dict[str, object]:
        """Reset synthetic state and populate the requested scenario."""
        try:
            runner = self._scenarios[name]
        except KeyError as exc:
            raise ValueError(f"Unknown scenario: {name}") from exc
        self._event_store.clear()
        self._context_registry.clear()
        return runner()

    def spawn_synthetic_agent(
        self,
        agent_id: str,
        *,
        parent_agent_id: str | None = None,
        prompt: str,
        scenario_name: str = "manual",
    ) -> dict[str, object]:
        if parent_agent_id and self._context_registry.get(parent_agent_id) is None:
            raise ValueError(f"Unknown parent agent: {parent_agent_id}")
        parent_snapshot = self._context_registry.get(parent_agent_id) if parent_agent_id else None
        root_agent_id = parent_snapshot.root_agent_id if parent_snapshot else agent_id
        self._spawn(
            agent_id,
            parent_agent_id=parent_agent_id,
            root_agent_id=root_agent_id,
            prompt=prompt,
            scenario_name=scenario_name,
        )
        return {"agent_id": agent_id, "parent_agent_id": parent_agent_id, "root_agent_id": root_agent_id}

    def reparent_agent(self, agent_id: str, new_parent_agent_id: str | None) -> dict[str, object]:
        snapshot = self._context_registry.get(agent_id)
        if snapshot is None:
            raise ValueError(f"Unknown agent: {agent_id}")
        if new_parent_agent_id and self._context_registry.get(new_parent_agent_id) is None:
            raise ValueError(f"Unknown parent agent: {new_parent_agent_id}")
        lineage_path = self._lineage_path(agent_id, new_parent_agent_id)
        root_agent_id = lineage_path[0]
        self._context_registry.register(
            AgentContextSnapshot(
                **{
                    **snapshot.to_dict(),
                    "parent_agent_id": new_parent_agent_id,
                    "root_agent_id": root_agent_id,
                    "lineage_path": lineage_path,
                }
            )
        )
        self._event_store.append(
            new_swarm_event(
                "agent_reparented",
                agent_id=agent_id,
                parent_agent_id=new_parent_agent_id,
                root_agent_id=root_agent_id,
                session_id=snapshot.session_id,
                payload={"new_parent_agent_id": new_parent_agent_id},
            )
        )
        return {"agent_id": agent_id, "new_parent_agent_id": new_parent_agent_id}

    def remove_agent(self, agent_id: str) -> dict[str, object]:
        snapshot = self._context_registry.get(agent_id)
        if snapshot is None:
            raise ValueError(f"Unknown agent: {agent_id}")
        to_remove = [
            child_id
            for child_id, child_snapshot in self._context_registry.snapshots().items()
            if child_snapshot.lineage_path[: len(snapshot.lineage_path)] == snapshot.lineage_path
        ]
        for child_id in to_remove:
            self._context_registry.remove(child_id)
        self._event_store.append(
            new_swarm_event(
                "agent_removed",
                agent_id=agent_id,
                parent_agent_id=snapshot.parent_agent_id,
                root_agent_id=snapshot.root_agent_id or agent_id,
                session_id=snapshot.session_id,
            )
        )
        return {"agent_id": agent_id, "removed": True}

    def _single_child(self) -> dict[str, object]:
        self._spawn("main", prompt="Coordinate the scenario.", scenario_name="single_child")
        self._spawn(
            "sub1",
            parent_agent_id="main",
            root_agent_id="main",
            prompt="Collect one child task.",
            scenario_name="single_child",
        )
        self._send("main", "sub1", "Run a deterministic child flow.")
        return {"scenario": "single_child", "root_agent_id": "main", "agent_ids": ["main", "sub1"]}

    def _two_level_fanout(self) -> dict[str, object]:
        self._spawn(
            "main",
            prompt="Coordinate the deterministic fanout scenario.",
            scenario_name="two_level_fanout",
        )
        self._spawn(
            "sub1",
            parent_agent_id="main",
            root_agent_id="main",
            prompt="Manage children A and B.",
            scenario_name="two_level_fanout",
        )
        self._spawn(
            "A",
            parent_agent_id="sub1",
            root_agent_id="main",
            prompt="Leaf worker A.",
            scenario_name="two_level_fanout",
        )
        self._spawn(
            "B",
            parent_agent_id="sub1",
            root_agent_id="main",
            prompt="Leaf worker B.",
            scenario_name="two_level_fanout",
        )
        self._send("main", "sub1", "Create a two-leaf fanout.")
        self._send("sub1", "A", "Handle branch A.")
        self._send("sub1", "B", "Handle branch B.")
        return {
            "scenario": "two_level_fanout",
            "root_agent_id": "main",
            "agent_ids": ["main", "sub1", "A", "B"],
        }

    def _approval_on_leaf(self) -> dict[str, object]:
        result = self._two_level_fanout()
        self._event_store.append(
            new_swarm_event(
                "permission_requested",
                agent_id="B",
                parent_agent_id="sub1",
                root_agent_id="main",
                session_id="B-session",
                correlation_id="approval-on-leaf",
                payload={
                    "tool_name": "bash",
                    "status": "pending",
                    "response_mode": "legacy",
                    "worker_id": "B",
                    "approver_id": "main",
                    "team_name": "default",
                },
            )
        )
        return {
            **result,
            "scenario": "approval_on_leaf",
            "approval_correlation_id": "approval-on-leaf",
        }

    def _spawn(
        self,
        agent_id: str,
        *,
        parent_agent_id: str | None = None,
        root_agent_id: str | None = None,
        prompt: str,
        scenario_name: str,
    ) -> None:
        resolved_root = root_agent_id or agent_id
        lineage_path = self._lineage_path(agent_id, parent_agent_id)
        self._context_registry.register(
            AgentContextSnapshot(
                agent_id=agent_id,
                session_id=f"{agent_id}-session",
                parent_agent_id=parent_agent_id,
                root_agent_id=resolved_root,
                lineage_path=lineage_path,
                prompt=prompt,
                system_prompt="Synthetic scenario agent",
                metadata={"synthetic": True, "scenario": scenario_name},
            )
        )
        self._event_store.append(
            new_swarm_event(
                "agent_spawned",
                agent_id=agent_id,
                parent_agent_id=parent_agent_id,
                root_agent_id=resolved_root,
                session_id=f"{agent_id}-session",
                payload={
                    "name": agent_id,
                    "team": "default",
                    "lineage_path": list(lineage_path),
                    "synthetic": True,
                },
            )
        )
        self._event_store.append(
            new_swarm_event(
                "agent_became_running",
                agent_id=agent_id,
                parent_agent_id=parent_agent_id,
                root_agent_id=resolved_root,
                session_id=f"{agent_id}-session",
                payload={"status": "running", "synthetic": True},
            )
        )

    def _send(self, from_agent: str, to_agent: str, text: str) -> None:
        root_agent_id = self._context_registry.get(to_agent).root_agent_id or to_agent
        parent_agent_id = self._context_registry.get(to_agent).parent_agent_id
        correlation_id = f"{from_agent}->{to_agent}"
        payload = {"from_agent": from_agent, "to_agent": to_agent, "text": text, "route_kind": "synthetic"}
        for event_type in ("message_send_requested", "message_routed", "message_delivered"):
            self._event_store.append(
                new_swarm_event(
                    event_type,  # type: ignore[arg-type]
                    agent_id=to_agent,
                    parent_agent_id=parent_agent_id,
                    root_agent_id=root_agent_id,
                    session_id=f"{to_agent}-session",
                    correlation_id=correlation_id,
                    payload=payload,
                )
            )

    def _lineage_path(self, agent_id: str, parent_agent_id: str | None) -> tuple[str, ...]:
        if parent_agent_id is None:
            return (agent_id,)
        parent = self._context_registry.get(parent_agent_id)
        if parent is None:
            return (parent_agent_id, agent_id)
        return parent.lineage_path + (agent_id,)
