"""Hybrid routing for agent-to-agent swarm messages."""

from __future__ import annotations

from typing import Any, Callable

from openharness.swarm.event_store import EventStore, get_event_store
from openharness.swarm.events import new_swarm_event
from openharness.swarm.registry import get_backend_registry
from openharness.swarm.types import TeammateMessage


class MessageRouter:
    """Route swarm messages while emitting structured observability events."""

    def __init__(self, executor_factory: Callable[[], Any] | None = None) -> None:
        self._executor_factory = executor_factory

    async def route_message(
        self,
        *,
        target_agent_id: str,
        message: TeammateMessage,
        parent_agent_id: str | None,
        root_agent_id: str,
        session_id: str | None,
        event_store: EventStore | None = None,
    ) -> dict[str, str | None]:
        """Deliver one message to a target agent through the active backend."""
        route_kind = "parent_child" if parent_agent_id == target_agent_id else "explicit"
        store = event_store if event_store is not None else get_event_store()
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

        executor = self._resolve_executor(target_agent_id)
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

    def _resolve_executor(self, target_agent_id: str):
        if self._executor_factory is not None:
            return self._executor_factory()
        return self._default_executor_factory(target_agent_id)

    @staticmethod
    def _default_executor_factory(target_agent_id: str):
        registry = get_backend_registry()
        backend_type = MessageRouter._recorded_backend_type(target_agent_id)
        if backend_type and backend_type in registry.available_backends():
            return registry.get_executor(backend_type)
        try:
            return registry.get_executor("in_process")
        except KeyError:
            try:
                return registry.get_executor("subprocess")
            except KeyError:
                return registry.get_executor()

    @staticmethod
    def _recorded_backend_type(target_agent_id: str) -> str | None:
        for event in reversed(get_event_store().all_events()):
            if event.event_type != "agent_spawned" or event.agent_id != target_agent_id:
                continue
            backend_type = event.payload.get("backend_type")
            if isinstance(backend_type, str) and backend_type:
                return backend_type
        return None
