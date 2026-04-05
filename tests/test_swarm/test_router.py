"""Tests for hybrid swarm message routing."""

from __future__ import annotations

import pytest

from openharness.swarm.event_store import get_event_store
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
