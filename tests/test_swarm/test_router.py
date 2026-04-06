"""Tests for hybrid swarm message routing."""

from __future__ import annotations

import pytest

from openharness.swarm.event_store import EventStore, get_event_store
from openharness.swarm.events import new_swarm_event
from openharness.swarm.router import MessageRouter
from openharness.swarm.types import TeammateMessage


@pytest.mark.asyncio
async def test_router_routes_explicit_messages_and_emits_events():
    delivered = []
    store = get_event_store()
    store.clear()

    class FakeExecutor:
        async def send_message(self, agent_id, message):
            delivered.append((agent_id, message))

    router = MessageRouter(lambda: FakeExecutor())
    result = await router.route_message(
        target_agent_id="worker@demo",
        message=TeammateMessage(text="do work", from_agent="leader@demo"),
        parent_agent_id=None,
        root_agent_id="leader@demo",
        session_id="root-session",
    )

    assert result["route_kind"] == "explicit"
    assert delivered == [("worker@demo", TeammateMessage(text="do work", from_agent="leader@demo"))]
    assert [event.event_type for event in store.events_for_agent("worker@demo")] == [
        "message_send_requested",
        "message_routed",
        "message_delivered",
    ]


@pytest.mark.asyncio
async def test_router_marks_parent_child_routes():
    delivered = []

    class FakeExecutor:
        async def send_message(self, agent_id, message):
            delivered.append((agent_id, message))

    router = MessageRouter(lambda: FakeExecutor())
    result = await router.route_message(
        target_agent_id="leader@demo",
        message=TeammateMessage(text="status?", from_agent="worker@demo"),
        parent_agent_id="leader@demo",
        root_agent_id="leader@demo",
        session_id="worker-session",
    )

    assert result["route_kind"] == "parent_child"
    assert delivered[0][0] == "leader@demo"


@pytest.mark.asyncio
async def test_router_emits_failure_event_on_delivery_error():
    store = get_event_store()
    store.clear()

    class FailingExecutor:
        async def send_message(self, agent_id, message):
            raise ValueError("missing target")

    router = MessageRouter(lambda: FailingExecutor())
    with pytest.raises(ValueError, match="missing target"):
        await router.route_message(
            target_agent_id="ghost@demo",
            message=TeammateMessage(text="ping", from_agent="leader@demo"),
            parent_agent_id=None,
            root_agent_id="leader@demo",
            session_id="root-session",
        )

    assert [event.event_type for event in store.events_for_agent("ghost@demo")] == [
        "message_send_requested",
        "message_routed",
        "message_delivery_failed",
    ]


@pytest.mark.asyncio
async def test_router_writes_to_explicit_event_store():
    """When event_store is passed, routing events must not go to the global store."""
    global_store = get_event_store()
    global_store.clear()
    custom = EventStore()

    class FakeExecutor:
        async def send_message(self, agent_id, message):
            pass

    router = MessageRouter(lambda: FakeExecutor())
    await router.route_message(
        target_agent_id="worker@demo",
        message=TeammateMessage(text="hi", from_agent="leader@demo"),
        parent_agent_id=None,
        root_agent_id="leader@demo",
        session_id="s1",
        event_store=custom,
    )

    assert len(global_store.all_events()) == 0
    assert [e.event_type for e in custom.all_events()] == [
        "message_send_requested",
        "message_routed",
        "message_delivered",
    ]


@pytest.mark.asyncio
async def test_router_prefers_recorded_backend_for_spawned_agent(monkeypatch):
    store = get_event_store()
    store.clear()
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker@demo",
            payload={"backend_type": "subprocess"},
        )
    )

    delivered: list[tuple[str, str, TeammateMessage]] = []

    class FakeExecutor:
        def __init__(self, backend_type: str) -> None:
            self.backend_type = backend_type

        async def send_message(self, agent_id, message):
            delivered.append((self.backend_type, agent_id, message))

    class FakeRegistry:
        def __init__(self) -> None:
            self._executors = {
                "in_process": FakeExecutor("in_process"),
                "subprocess": FakeExecutor("subprocess"),
            }

        def get_executor(self, backend_type=None):
            assert backend_type in self._executors
            return self._executors[backend_type]

        def available_backends(self):
            return list(self._executors.keys())

    monkeypatch.setattr("openharness.swarm.router.get_backend_registry", lambda: FakeRegistry())

    router = MessageRouter()
    await router.route_message(
        target_agent_id="worker@demo",
        message=TeammateMessage(text="ping", from_agent="leader@demo"),
        parent_agent_id=None,
        root_agent_id="leader@demo",
        session_id="root-session",
    )

    assert delivered == [
        ("subprocess", "worker@demo", TeammateMessage(text="ping", from_agent="leader@demo"))
    ]
