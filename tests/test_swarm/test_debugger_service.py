"""Tests for the swarm debugger service and runtime editor hooks."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from openharness.swarm.context_registry import AgentContextRegistry, AgentContextSnapshot
from openharness.swarm.debugger import SwarmDebuggerService
from openharness.swarm.event_store import EventStore
from openharness.swarm.events import new_swarm_event


def _seed_store() -> EventStore:
    store = EventStore()
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="root-session",
            payload={"name": "leader", "team": "demo"},
        )
    )
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="worker@demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            payload={"name": "worker", "team": "demo", "lineage_path": ["leader@demo", "worker@demo"]},
        )
    )
    store.append(
        new_swarm_event(
            "message_delivered",
            agent_id="worker@demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            correlation_id="corr-1",
            payload={"from_agent": "leader@demo", "to_agent": "worker@demo", "text": "do work"},
        )
    )
    store.append(
        new_swarm_event(
            "permission_requested",
            agent_id="worker@demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            correlation_id="perm-1",
            payload={"tool_name": "bash", "status": "pending"},
        )
    )
    return store


def test_debugger_service_exposes_snapshot_and_playback():
    store = _seed_store()
    contexts = AgentContextRegistry()
    contexts.register(
        AgentContextSnapshot(
            agent_id="worker@demo",
            session_id="worker-session",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            lineage_path=("leader@demo", "worker@demo"),
            prompt="do work",
            system_prompt="You are a worker.",
            messages=("user: do work",),
        )
    )
    service = SwarmDebuggerService(event_store=store, context_registry=contexts)

    snapshot = service.snapshot()
    assert snapshot["tree"]["roots"] == ["leader@demo"]
    assert snapshot["timeline"][0]["event_type"] == "agent_spawned"
    assert snapshot["message_graph"][0]["text"] == "do work"
    assert snapshot["approval_queue"][0]["correlation_id"] == "perm-1"
    assert snapshot["contexts"]["worker@demo"]["prompt"] == "do work"
    assert snapshot["overview"]["agent_count"] == 2
    assert snapshot["overview"]["message_count"] == 1
    assert snapshot["overview"]["pending_approvals"] == 1
    assert snapshot["overview"]["max_depth"] == 2
    assert snapshot["activity"]["worker@demo"]["messages_received"] == 1
    assert snapshot["activity"]["worker@demo"]["event_counts"]["agent_spawned"] == 1

    playback = service.playback(event_limit=2)
    assert len(playback["timeline"]) == 2
    assert playback["tree"]["nodes"]["worker@demo"]["parent_agent_id"] == "leader@demo"


def test_debugger_service_can_run_builtin_scenario():
    service = SwarmDebuggerService(event_store=EventStore(), context_registry=AgentContextRegistry())

    result = service.run_scenario("two_level_fanout")

    assert result["scenario"] == "two_level_fanout"
    snapshot = service.snapshot()
    assert snapshot["tree"]["roots"] == ["main"]
    assert snapshot["tree"]["nodes"]["sub1"]["children"] == ["A", "B"]
    assert snapshot["overview"]["max_depth"] == 3
    assert snapshot["overview"]["leaf_agents"] == ["A", "B"]
    assert snapshot["activity"]["sub1"]["children"] == ["A", "B"]
    assert snapshot["scenario_view"]["levels"][0]["agents"] == ["main"]
    assert snapshot["scenario_view"]["levels"][1]["agents"] == ["sub1"]
    assert snapshot["scenario_view"]["levels"][2]["agents"] == ["A", "B"]
    assert snapshot["scenario_view"]["route_summary"]["sub1"] == ["A", "B"]


@pytest.mark.asyncio
async def test_debugger_service_supports_controls_and_context_patch():
    store = _seed_store()
    contexts = AgentContextRegistry()
    contexts.register(
        AgentContextSnapshot(
            agent_id="worker@demo",
            session_id="worker-session",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            lineage_path=("leader@demo", "worker@demo"),
            prompt="do work",
            system_prompt="You are a worker.",
            messages=("user: do work",),
        )
    )
    calls: list[tuple[str, str]] = []

    async def _send(agent_id: str, message: str) -> dict[str, str]:
        calls.append(("send", f"{agent_id}:{message}"))
        return {"route_kind": "explicit", "target_agent_id": agent_id}

    async def _pause(agent_id: str) -> bool:
        calls.append(("pause", agent_id))
        return True

    async def _resume(agent_id: str) -> bool:
        calls.append(("resume", agent_id))
        return True

    async def _stop(agent_id: str) -> bool:
        calls.append(("stop", agent_id))
        return True

    service = SwarmDebuggerService(
        event_store=store,
        context_registry=contexts,
        send_message=_send,
        pause_agent=_pause,
        resume_agent=_resume,
        stop_agent=_stop,
    )

    await service.send_message("worker@demo", "debug ping")
    await service.pause_agent("worker@demo")
    await service.resume_agent("worker@demo")
    await service.stop_agent("worker@demo")
    updated = service.apply_context_patch(
        "worker@demo",
        patch={"messages": ["user: do work", "system: patch"], "compacted_summary": "patched"},
        base_version=1,
    )
    approval = await service.resolve_approval("perm-1", status="approved")

    assert calls == [
        ("send", "worker@demo:debug ping"),
        ("pause", "worker@demo"),
        ("resume", "worker@demo"),
        ("stop", "worker@demo"),
    ]
    assert updated.context_version == 2
    assert updated.compacted_summary == "patched"
    assert approval["status"] == "approved"

    timeline_types = [item["event_type"] for item in service.snapshot()["timeline"]]
    assert "agent_paused" in timeline_types
    assert "agent_resumed" in timeline_types
    assert "context_patch_applied" in timeline_types
    assert "permission_resolved" in timeline_types


def test_context_registry_persists_snapshots_to_disk(tmp_path):
    registry = AgentContextRegistry(storage_dir=tmp_path)
    registry.register(
        AgentContextSnapshot(
            agent_id="worker@demo",
            session_id="worker-session",
            prompt="do work",
        )
    )
    reloaded = AgentContextRegistry(storage_dir=tmp_path)
    assert reloaded.get("worker@demo") is not None
    assert reloaded.get("worker@demo").prompt == "do work"


def test_context_registry_refreshes_from_disk_on_read(tmp_path):
    reader = AgentContextRegistry(storage_dir=tmp_path)
    writer = AgentContextRegistry(storage_dir=tmp_path)
    writer.register(
        AgentContextSnapshot(
            agent_id="worker@demo",
            session_id="worker-session",
            prompt="do work",
        )
    )

    assert reader.get("worker@demo") is not None
    assert reader.get("worker@demo").prompt == "do work"


@pytest.mark.asyncio
async def test_debugger_service_resolve_approval_uses_request_event(monkeypatch):
    store = _seed_store()
    store.append(
        new_swarm_event(
            "permission_resolved",
            agent_id="worker@demo",
            parent_agent_id="leader@demo",
            root_agent_id="leader@demo",
            session_id="worker-session",
            correlation_id="perm-1",
            payload={"status": "approved"},
        )
    )
    legacy_send = AsyncMock()
    mailbox_send = AsyncMock()
    monkeypatch.setattr("openharness.swarm.debugger.send_permission_response", legacy_send)
    monkeypatch.setattr("openharness.swarm.debugger.send_permission_response_via_mailbox", mailbox_send)

    service = SwarmDebuggerService(event_store=store, context_registry=AgentContextRegistry())
    result = await service.resolve_approval("perm-1", status="approved")

    assert result["status"] == "approved"
    legacy_send.assert_called_once()
    mailbox_send.assert_not_called()


@pytest.mark.asyncio
async def test_debugger_service_resolve_approval_rejects_missing_request():
    service = SwarmDebuggerService(event_store=EventStore(), context_registry=AgentContextRegistry())
    with pytest.raises(ValueError, match="No permission request found"):
        await service.resolve_approval("missing", status="approved")
