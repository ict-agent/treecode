"""Structured swarm event schema used by runtime graph and debugger views."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


SwarmEventType = Literal[
    "agent_spawn_requested",
    "agent_spawned",
    "agent_attached_to_parent",
    "agent_became_running",
    "turn_started",
    "message_send_requested",
    "message_routed",
    "message_delivered",
    "message_consumed",
    "message_delivery_failed",
    "tool_called",
    "tool_completed",
    "permission_requested",
    "permission_resolved",
    "context_compacted",
    "agent_paused",
    "agent_resumed",
    "agent_finished",
    "agent_reparented",
    "agent_removed",
    "context_patch_requested",
    "context_patch_applied",
    "context_patch_rejected",
    "manual_message_injected",
    "agent_rewound_to_event",
]


@dataclass(frozen=True)
class SwarmEvent:
    """A single normalized runtime event emitted by the swarm layer."""

    event_id: str
    event_type: SwarmEventType
    timestamp: float
    agent_id: str
    root_agent_id: str
    parent_agent_id: str | None = None
    session_id: str | None = None
    correlation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event to a JSON-friendly dictionary."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "root_agent_id": self.root_agent_id,
            "parent_agent_id": self.parent_agent_id,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SwarmEvent":
        """Deserialize a previously serialized swarm event."""
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            timestamp=float(data["timestamp"]),
            agent_id=data["agent_id"],
            root_agent_id=data["root_agent_id"],
            parent_agent_id=data.get("parent_agent_id"),
            session_id=data.get("session_id"),
            correlation_id=data.get("correlation_id"),
            payload=dict(data.get("payload", {})),
        )


def new_swarm_event(
    event_type: SwarmEventType,
    *,
    agent_id: str,
    root_agent_id: str,
    parent_agent_id: str | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> SwarmEvent:
    """Create a new event with generated ID and timestamp."""
    return SwarmEvent(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        timestamp=time.time(),
        agent_id=agent_id,
        root_agent_id=root_agent_id,
        parent_agent_id=parent_agent_id,
        session_id=session_id,
        correlation_id=correlation_id,
        payload=dict(payload or {}),
    )
