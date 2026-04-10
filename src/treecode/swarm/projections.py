"""Debugger-facing projections derived from structured swarm events."""

from __future__ import annotations

from dataclasses import dataclass, field

from typing import Any

from treecode.swarm.events import SwarmEvent
from treecode.swarm.runtime_graph import AgentNode, RuntimeGraph

_TOOL_RECENT_MAX = 50
"""Cap recent tool rows in the snapshot projection (FIFO tail)."""


@dataclass
class SwarmProjection:
    """Materialized views used by tree, timeline, and approval UIs."""

    graph: RuntimeGraph = field(default_factory=RuntimeGraph)
    _timeline: list[SwarmEvent] = field(default_factory=list)
    _message_edges: list[dict[str, str | None]] = field(default_factory=list)
    _approval_queue: dict[str, dict[str, str | None]] = field(default_factory=dict)
    _tool_recent: list[dict[str, Any]] = field(default_factory=list)

    def apply(self, event: SwarmEvent) -> None:
        """Apply one event to all derived views."""
        self._timeline.append(event)

        if event.event_type == "agent_spawned":
            existing = self.graph.get_node(event.agent_id)
            self.graph.add_node(
                self._agent_node_for(
                    event,
                    parent_agent_id=event.parent_agent_id,
                    lineage_path=self._lineage_for(event),
                    status=existing.status if existing is not None else "starting",
                )
            )
        elif event.event_type in {"agent_became_running", "agent_paused", "agent_resumed", "agent_finished"}:
            status_map = {
                "agent_became_running": "running",
                "agent_paused": "paused",
                "agent_resumed": "running",
                "agent_finished": "finished",
            }
            self._ensure_agent_node(event)
            self.graph.update_status(event.agent_id, status_map[event.event_type])
        elif event.event_type == "agent_reparented":
            self._ensure_agent_node(event)
            self.graph.reparent(
                event.agent_id,
                new_parent_agent_id=event.payload.get("new_parent_agent_id"),
            )
        elif event.event_type == "agent_removed":
            if self.graph.get_node(event.agent_id) is not None:
                self.graph.remove_node(event.agent_id)

        if event.event_type in {"message_delivered", "message_delivery_failed"}:
            self._message_edges.append(
                {
                    "from_agent": str(event.payload.get("from_agent")),
                    "to_agent": str(event.payload.get("to_agent", event.agent_id)),
                    "correlation_id": event.correlation_id,
                    "event_type": event.event_type,
                    "text": str(event.payload.get("text", "")),
                }
            )
        elif event.event_type == "manual_message_injected":
            self._message_edges.append(
                {
                    "from_agent": "debugger",
                    "to_agent": str(event.agent_id),
                    "correlation_id": event.correlation_id,
                    "event_type": event.event_type,
                    "text": str(event.payload.get("message", "")),
                }
            )
        elif event.event_type == "assistant_message":
            self._message_edges.append(
                {
                    "from_agent": str(event.agent_id),
                    "to_agent": "user",
                    "correlation_id": event.correlation_id,
                    "event_type": event.event_type,
                    "text": str(event.payload.get("text", "")),
                }
            )

        if event.event_type == "tool_called":
            self._record_tool_event(event, phase="called")
        elif event.event_type == "tool_completed":
            self._record_tool_event(event, phase="completed")

        if event.event_type == "permission_requested":
            key = event.correlation_id or event.event_id
            self._approval_queue[key] = {
                "agent_id": event.agent_id,
                "correlation_id": key,
                "tool_name": str(event.payload.get("tool_name", "")),
                "status": str(event.payload.get("status", "pending")),
            }
        elif event.event_type == "permission_resolved":
            key = event.correlation_id or event.event_id
            current = self._approval_queue.get(
                key,
                {
                    "agent_id": event.agent_id,
                    "correlation_id": key,
                    "tool_name": str(event.payload.get("tool_name", "")),
                },
            )
            current["status"] = str(event.payload.get("status", "resolved"))
            self._approval_queue[key] = current

    def tree_snapshot(self) -> dict[str, object]:
        """Return the current tree snapshot."""
        return self.graph.snapshot()

    def timeline(self) -> tuple[SwarmEvent, ...]:
        """Return the ordered event timeline."""
        return tuple(self._timeline)

    def message_graph(self) -> tuple[dict[str, str | None], ...]:
        """Return normalized message edges for visualization."""
        return tuple(self._message_edges)

    def approval_queue(self) -> tuple[dict[str, str | None], ...]:
        """Return pending and resolved approval items."""
        return tuple(self._approval_queue.values())

    def tool_recent(self) -> tuple[dict[str, Any], ...]:
        """Recent tool_called / tool_completed rows for console summary (bounded)."""
        return tuple(self._tool_recent)

    def _record_tool_event(self, event: SwarmEvent, *, phase: str) -> None:
        row: dict[str, Any] = {
            "phase": phase,
            "agent_id": event.agent_id,
            "tool_name": str(event.payload.get("tool_name", "")),
            "source": str(event.payload.get("source", "")),
            "event_id": event.event_id,
            "correlation_id": event.correlation_id,
        }
        if phase == "called":
            ti = event.payload.get("tool_input")
            if isinstance(ti, dict):
                row["tool_input_preview"] = {k: str(v)[:80] for k, v in list(ti.items())[:8]}
        else:
            row["is_error"] = bool(event.payload.get("is_error", False))
            row["output_preview"] = str(event.payload.get("output", ""))[:200]
        self._tool_recent.append(row)
        if len(self._tool_recent) > _TOOL_RECENT_MAX:
            self._tool_recent = self._tool_recent[-_TOOL_RECENT_MAX:]

    def _lineage_for(self, event: SwarmEvent) -> tuple[str, ...]:
        payload_path = event.payload.get("lineage_path")
        if isinstance(payload_path, (list, tuple)) and payload_path:
            return tuple(str(item) for item in payload_path)
        if event.parent_agent_id:
            parent = self.graph.get_node(event.parent_agent_id)
            if parent and parent.lineage_path:
                return parent.lineage_path + (event.agent_id,)
            return (event.parent_agent_id, event.agent_id)
        return (event.agent_id,)

    def _ensure_agent_node(self, event: SwarmEvent) -> None:
        if self.graph.get_node(event.agent_id) is not None:
            return
        self.graph.add_node(
            self._agent_node_for(
                event,
                parent_agent_id=event.parent_agent_id,
                lineage_path=self._lineage_for(event),
            )
        )

    def _agent_node_for(
        self,
        event: SwarmEvent,
        *,
        parent_agent_id: str | None,
        lineage_path: tuple[str, ...],
        status: str = "starting",
    ) -> AgentNode:
        name, team = self._split_agent_id(event.agent_id)
        return AgentNode(
            agent_id=event.agent_id,
            name=str(event.payload.get("name", name)),
            team=str(event.payload.get("team", team)),
            parent_agent_id=parent_agent_id,
            root_agent_id=event.root_agent_id,
            session_id=event.session_id,
            lineage_path=lineage_path,
            status=status,
            backend_type=(
                str(event.payload.get("backend_type"))
                if event.payload.get("backend_type") is not None
                else None
            ),
            spawn_mode=(
                str(event.payload.get("spawn_mode"))
                if event.payload.get("spawn_mode") is not None
                else None
            ),
            synthetic=bool(event.payload.get("synthetic", False)),
        )

    @staticmethod
    def _split_agent_id(agent_id: str) -> tuple[str, str]:
        if "@" in agent_id:
            return agent_id.split("@", 1)
        return agent_id, "default"
