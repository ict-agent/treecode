"""Tests for recursive gather protocol helpers."""

from __future__ import annotations

import pytest

from treecode.swarm.event_store import EventStore
from treecode.swarm.gather_spec import GatherSpec
from treecode.swarm.gather import (
    GatherNodeResult,
    assemble_gather_result,
    emit_gather_failed,
    emit_gather_requested,
    emit_gather_result,
    run_recursive_gather,
    wait_for_child_gather_results,
)


def test_emit_gather_lifecycle_events_share_correlation_id():
    store = EventStore()

    emit_gather_requested(
        event_store=store,
        gather_id="g-1",
        agent_id="parent@default",
        root_agent_id="main@default",
        parent_agent_id="main@default",
        session_id="sess-parent",
        target_agent_ids=["child@default"],
        request="collect handshake",
        spec_name="gather_handshake",
    )
    emit_gather_result(
        event_store=store,
        gather_id="g-1",
        agent_id="parent@default",
        root_agent_id="main@default",
        parent_agent_id="main@default",
        session_id="sess-parent",
        result=GatherNodeResult(
            agent_id="parent@default",
            status="ok",
            self_result={"ready": True},
            children=[],
        ),
    )
    emit_gather_failed(
        event_store=store,
        gather_id="g-1",
        agent_id="child@default",
        root_agent_id="main@default",
        parent_agent_id="parent@default",
        session_id="sess-child",
        error="timeout",
    )

    events = store.all_events()
    assert [event.event_type for event in events] == [
        "gather_requested",
        "gather_result_reported",
        "gather_failed",
    ]
    assert {event.correlation_id for event in events} == {"g-1"}


@pytest.mark.asyncio
async def test_wait_for_child_gather_results_returns_results_by_child_id():
    store = EventStore()
    emit_gather_result(
        event_store=store,
        gather_id="g-2",
        agent_id="child-b@default",
        root_agent_id="main@default",
        parent_agent_id="parent@default",
        session_id="sess-b",
        result=GatherNodeResult(
            agent_id="child-b@default",
            status="ok",
            self_result={"ready": False},
            children=[],
        ),
    )
    emit_gather_result(
        event_store=store,
        gather_id="g-2",
        agent_id="child-a@default",
        root_agent_id="main@default",
        parent_agent_id="parent@default",
        session_id="sess-a",
        result=GatherNodeResult(
            agent_id="child-a@default",
            status="ok",
            self_result={"ready": True},
            children=[],
        ),
    )

    results = await wait_for_child_gather_results(
        event_store=store,
        gather_id="g-2",
        child_agent_ids=["child-a@default", "child-b@default"],
        timeout_seconds=0.01,
    )

    assert list(results.keys()) == ["child-a@default", "child-b@default"]
    assert results["child-a@default"].self_result == {"ready": True}
    assert results["child-b@default"].self_result == {"ready": False}


@pytest.mark.asyncio
async def test_wait_for_child_gather_results_marks_missing_children_as_timeout():
    store = EventStore()
    emit_gather_result(
        event_store=store,
        gather_id="g-3",
        agent_id="child-a@default",
        root_agent_id="main@default",
        parent_agent_id="parent@default",
        session_id="sess-a",
        result=GatherNodeResult(
            agent_id="child-a@default",
            status="ok",
            self_result={"ready": True},
            children=[],
        ),
    )

    results = await wait_for_child_gather_results(
        event_store=store,
        gather_id="g-3",
        child_agent_ids=["child-a@default", "child-b@default"],
        timeout_seconds=0,
    )

    assert results["child-a@default"].status == "ok"
    assert results["child-b@default"].status == "timeout"
    assert results["child-b@default"].self_result is None


def test_assemble_gather_result_preserves_topology_order():
    child_b = GatherNodeResult(
        agent_id="child-b@default",
        status="ok",
        self_result={"ready": False},
        children=[],
    )
    child_a = GatherNodeResult(
        agent_id="child-a@default",
        status="ok",
        self_result={"ready": True},
        children=[],
    )

    result = assemble_gather_result(
        agent_id="parent@default",
        self_result={"ready": True},
        child_results={
            "child-b@default": child_b,
            "child-a@default": child_a,
        },
        child_agent_ids=["child-a@default", "child-b@default"],
        ordering="topology",
        errors=["one child timed out earlier"],
    )

    assert result.agent_id == "parent@default"
    assert [child.agent_id for child in result.children] == [
        "child-a@default",
        "child-b@default",
    ]
    assert result.errors == ["one child timed out earlier"]


def test_assemble_gather_result_preserves_summary_text():
    result = assemble_gather_result(
        agent_id="parent@default",
        self_result={"ready": True},
        child_results={},
        child_agent_ids=[],
        ordering="topology",
        summary_text="parent topology summary",
    )

    assert result.summary_text == "parent topology summary"


@pytest.mark.asyncio
async def test_run_recursive_gather_fans_out_internal_commands_and_assembles_result():
    store = EventStore()
    sent: list[tuple[str, str]] = []
    spec = GatherSpec(
        name="gather_handshake",
        description="Recursive handshake gather.",
        version=1,
        allow_none=True,
        timeout_seconds=1,
        ordering="topology",
        return_mode="tree",
        instructions="Return topology-like handshake payload.",
        path=None,  # type: ignore[arg-type]
    )

    async def send_to_agent(agent_id: str, command: str) -> None:
        sent.append((agent_id, command))
        emit_gather_result(
            event_store=store,
            gather_id="g-4",
            agent_id=agent_id,
            root_agent_id="main@default",
            parent_agent_id="parent@default",
            session_id=f"sess-{agent_id}",
            result=GatherNodeResult(
                agent_id=agent_id,
                status="ok",
                self_result={"ready": True, "agent_id": agent_id},
                children=[],
            ),
        )

    async def synthesize_node(*, child_results) -> dict[str, object]:
        assert list(child_results.keys()) == ["child-a@default", "child-b@default"]
        return {
            "self_result": {"ready": True, "agent_id": "parent@default"},
            "summary_text": "parent topology summary",
        }

    result = await run_recursive_gather(
        event_store=store,
        gather_id="g-4",
        current_agent_id="parent@default",
        root_agent_id="main@default",
        parent_agent_id="main@default",
        session_id="sess-parent",
        spec=spec,
        request="collect handshake",
        child_agent_ids=["child-a@default", "child-b@default"],
        send_to_agent=send_to_agent,
        synthesize_node=synthesize_node,
    )

    assert [agent_id for agent_id, _command in sent] == [
        "child-a@default",
        "child-b@default",
    ]
    assert all("/gather" in command for _agent_id, command in sent)
    assert result.agent_id == "parent@default"
    assert [child.agent_id for child in result.children] == [
        "child-a@default",
        "child-b@default",
    ]
    assert result.summary_text == "parent topology summary"
