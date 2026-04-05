"""Hybrid routing for agent-to-agent swarm messages."""

from __future__ import annotations

from typing import Any, Callable

from openharness.swarm.event_store import get_event_store
from openharness.swarm.events import new_swarm_event
from openharness.swarm.registry import get_backend_registry
from openharness.swarm.types import TeammateMessage


class MessageRouter:
    """Route swarm messages while emitting structured observability events."""

    def __init__(self, executor_factory: Callable[[], Any] | None = None) -> None:
        self._executor_factory = executor_factory or self._default_executor_factory

    async def route_message(
        self,
        *,
        target_agent_id: str,
        message: TeammateMessage,
        parent_agent_id: str | None,
        root_agent_id: str,
        session_id: str | None,
    ) -> dict[str, str | None]:
        """Deliver one message to a target agent through the active backend."""
        route_kind = "parent_child" if parent_agent_id == target_agent_id else "explicit"
        store = get_event_store()
        correlation_id = f"{message.from_agent}->{target_agent_id}:{message.timestamp or 'now'}"
        payload = {
            "from_agent": message.from_agent,
            "to_agent": target_agent_id,
            "text": message.text,
            "route_kind": route_kind,
        }
        store.append(
            new_swarm_event(
                "message_send_requested",
                agent_id=target_agent_id,
                parent_agent_id=parent_agent_id,
                root_agent_id=root_agent_id,
                session_id=session_id,
                correlation_id=correlation_id,
                payload=payload,
            )
        )
        store.append(
            new_swarm_event(
                "message_routed",
                agent_id=target_agent_id,
                parent_agent_id=parent_agent_id,
                root_agent_id=root_agent_id,
                session_id=session_id,
                correlation_id=correlation_id,
                payload=payload,
            )
        )

        executor = self._executor_factory()
        try:
            await executor.send_message(target_agent_id, message)
        except Exception:
            store.append(
                new_swarm_event(
                    "message_delivery_failed",
                    agent_id=target_agent_id,
                    parent_agent_id=parent_agent_id,
                    root_agent_id=root_agent_id,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    payload=payload,
                )
            )
            raise

        store.append(
            new_swarm_event(
                "message_delivered",
                agent_id=target_agent_id,
                parent_agent_id=parent_agent_id,
                root_agent_id=root_agent_id,
                session_id=session_id,
                correlation_id=correlation_id,
                payload=payload,
            )
        )
        return {
            "route_kind": route_kind,
            "target_agent_id": target_agent_id,
            "sender_agent_id": message.from_agent,
            "correlation_id": correlation_id,
        }

    @staticmethod
    def _default_executor_factory():
        registry = get_backend_registry()
        try:
            return registry.get_executor("in_process")
        except KeyError:
            try:
                return registry.get_executor("subprocess")
            except KeyError:
                return registry.get_executor()
