"""Tests for the swarm debugger service and runtime editor hooks."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from openharness.swarm.context_registry import AgentContextRegistry, AgentContextSnapshot
from openharness.swarm.debugger import SwarmDebuggerService, create_default_swarm_debugger_service
from openharness.swarm.event_store import EventStore, get_event_store
from openharness.swarm.events import new_swarm_event
from openharness.swarm.manager import AgentManager
from openharness.tasks.types import TaskRecord
from openharness.tools.base import ToolResult
from openharness.tools import create_default_tool_registry


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
            payload={
                "name": "worker",
                "team": "demo",
                "lineage_path": ["leader@demo", "worker@demo"],
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
            },
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
    assert snapshot["topology_view"] == "live"
    assert snapshot["available_topology_views"] == ["live", "raw_events"]
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
    assert snapshot["agents"]["worker@demo"]["backend_type"] == "subprocess"
    assert snapshot["agents"]["worker@demo"]["spawn_mode"] == "persistent"
    assert snapshot["agents"]["worker@demo"]["prompt"] == "do work"
    assert [item["item_type"] for item in snapshot["agents"]["worker@demo"]["feed"]] == [
        "prompt",
        "lifecycle",
        "incoming",
        "approval_request",
    ]

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


def test_debugger_service_archives_and_compares_runs(tmp_path):
    service = SwarmDebuggerService(
        event_store=EventStore(),
        context_registry=AgentContextRegistry(),
        archive_dir=tmp_path,
    )

    service.run_scenario("single_child")
    first = service.archive_current_run(label="first")
    service.run_scenario("two_level_fanout")
    second = service.archive_current_run(label="second")

    archives = service.list_archives()
    comparison = service.compare_runs(first["run_id"], second["run_id"])

    assert len(archives) == 2
    assert comparison["left_run_id"] == first["run_id"]
    assert comparison["right_run_id"] == second["run_id"]
    assert "agent_count" in comparison["differences"]


def test_debugger_service_scenario_does_not_clear_live_store():
    live_store = EventStore()
    live_store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="live@demo",
            root_agent_id="live@demo",
            session_id="live-session",
            payload={"name": "live", "team": "demo"},
        )
    )
    live_contexts = AgentContextRegistry()
    live_contexts.register(
        AgentContextSnapshot(
            agent_id="live@demo",
            session_id="live-session",
            prompt="live",
        )
    )
    service = SwarmDebuggerService(
        event_store=live_store,
        context_registry=live_contexts,
        reconcile_live_runtime=True,
    )

    service.run_scenario("single_child")

    assert live_store.events_for_agent("live@demo")
    assert live_contexts.get("live@demo") is not None


def test_debugger_service_can_switch_between_live_and_scenario_sources():
    live_store = EventStore()
    live_store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="live@demo",
            root_agent_id="live@demo",
            session_id="live-session",
            payload={"name": "live", "team": "demo", "backend_type": "subprocess", "task_id": "task-live"},
        )
    )
    live_contexts = AgentContextRegistry()
    live_contexts.register(
        AgentContextSnapshot(
            agent_id="live@demo",
            session_id="live-session",
            prompt="live",
        )
    )
    service = SwarmDebuggerService(
        event_store=live_store,
        context_registry=live_contexts,
        reconcile_live_runtime=True,
    )
    with patch(
        "openharness.swarm.topology_reader.load_persisted_task_record",
        lambda task_id: TaskRecord(
            id=task_id,
            type="in_process_teammate",
            status="running",
            description="demo",
            cwd=".",
            output_file=Path(".") / f"{task_id}.log",
            command="python -m openharness --backend-only",
        ),
    ):
        service.run_scenario("single_child")

        assert service.snapshot()["active_source"] == "scenario"
        assert service.snapshot()["tree"]["roots"] == ["main"]

        service.set_active_source("live")

        assert service.snapshot()["active_source"] == "live"
        assert service.snapshot()["tree"]["roots"] == ["live@demo"]


def test_debugger_service_live_snapshot_filters_stale_agents(monkeypatch, tmp_path):
    live_store = EventStore()
    live_store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            payload={
                "name": "worker",
                "team": "demo",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-worker",
            },
        )
    )
    live_store.append(
        new_swarm_event(
            "agent_became_running",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
        )
    )
    live_store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="stale@demo",
            root_agent_id="stale@demo",
            session_id="stale-session",
            payload={
                "name": "stale",
                "team": "demo",
                "backend_type": "subprocess",
                "spawn_mode": "persistent",
                "task_id": "task-stale",
            },
        )
    )
    live_contexts = AgentContextRegistry()
    live_contexts.register(
        AgentContextSnapshot(
            agent_id="worker@demo",
            session_id="worker-session",
            prompt="do work",
        )
    )
    live_contexts.register(
        AgentContextSnapshot(
            agent_id="stale@demo",
            session_id="stale-session",
            prompt="old work",
        )
    )

    def _load(task_id: str):
        status = "running" if task_id == "task-worker" else "completed"
        return TaskRecord(
            id=task_id,
            type="in_process_teammate",
            status=status,
            description="demo",
            cwd=str(tmp_path),
            output_file=tmp_path / f"{task_id}.log",
            command="python -m openharness --backend-only",
        )

    monkeypatch.setattr("openharness.swarm.topology_reader.load_persisted_task_record", _load)
    service = SwarmDebuggerService(
        event_store=live_store,
        context_registry=live_contexts,
        reconcile_live_runtime=True,
    )

    snapshot = service.snapshot()

    assert snapshot["topology_view"] == "live"
    assert snapshot["tree"]["roots"] == ["worker@demo"]
    assert "worker@demo" in snapshot["agents"]
    assert "stale@demo" not in snapshot["agents"]


def test_debugger_service_builds_agent_feed_for_cli_style_transcript():
    store = EventStore()
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            payload={"name": "worker", "team": "demo", "backend_type": "subprocess", "spawn_mode": "persistent"},
        )
    )
    store.append(
        new_swarm_event(
            "turn_started",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            payload={"message_count": 3},
        )
    )
    store.append(
        new_swarm_event(
            "message_delivered",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            correlation_id="msg-1",
            payload={"from_agent": "debugger@console", "to_agent": "worker@demo", "text": "investigate"},
        )
    )
    store.append(
        new_swarm_event(
            "tool_called",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            correlation_id="tool-1",
            payload={"tool_name": "brief", "tool_input": {"text": "investigate"}, "source": "model"},
        )
    )
    store.append(
        new_swarm_event(
            "tool_completed",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            correlation_id="tool-1",
            payload={"tool_name": "brief", "output": "summary", "is_error": False, "source": "model"},
        )
    )
    store.append(
        new_swarm_event(
            "assistant_message",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            correlation_id="assist-1",
            payload={"text": "Done.", "has_tool_uses": False},
        )
    )
    store.append(
        new_swarm_event(
            "permission_requested",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            correlation_id="perm-1",
            payload={"tool_name": "bash", "status": "pending"},
        )
    )
    store.append(
        new_swarm_event(
            "permission_resolved",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            correlation_id="perm-1",
            payload={"status": "approved"},
        )
    )
    store.append(
        new_swarm_event(
            "agent_finished",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            payload={"status": "completed"},
        )
    )
    contexts = AgentContextRegistry()
    contexts.register(
        AgentContextSnapshot(
            agent_id="worker@demo",
            session_id="worker-session",
            prompt="Investigate the issue",
        )
    )
    service = SwarmDebuggerService(event_store=store, context_registry=contexts)

    feed = service.snapshot()["agents"]["worker@demo"]["feed"]

    assert [item["item_type"] for item in feed] == [
        "prompt",
        "lifecycle",
        "turn_marker",
        "incoming",
        "tool_call",
        "tool_result",
        "assistant",
        "approval_request",
        "approval_result",
        "lifecycle",
    ]
    assert feed[3]["text"] == "investigate"
    assert feed[4]["tool_name"] == "brief"
    assert feed[5]["text"] == "summary"
    assert feed[6]["text"] == "Done."
    assert feed[7]["status"] == "pending"
    assert feed[8]["status"] == "approved"


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


@pytest.mark.asyncio
async def test_debugger_service_remove_agent_preserves_original_lineage_metadata():
    store = EventStore()
    contexts = AgentContextRegistry()
    manager = AgentManager(event_store=store, context_registry=contexts)
    manager.run_scenario("single_child")
    service = SwarmDebuggerService(event_store=store, context_registry=contexts)

    await service.remove_agent("sub1")

    removed = [event for event in store.all_events() if event.event_type == "agent_removed"][-1]
    assert removed.parent_agent_id == "main"
    assert removed.root_agent_id == "main"
    assert removed.session_id == "sub1-session"


@pytest.mark.asyncio
async def test_debugger_service_remove_agent_rejects_failed_stop():
    contexts = AgentContextRegistry()
    contexts.register(
        AgentContextSnapshot(
            agent_id="live@demo",
            session_id="live-session",
            root_agent_id="live@demo",
            metadata={"synthetic": False},
        )
    )
    service = SwarmDebuggerService(
        event_store=EventStore(),
        context_registry=contexts,
        stop_agent=lambda agent_id: __import__("asyncio").sleep(0, result=False),
    )

    with pytest.raises(ValueError, match="Failed to stop agent"):
        await service.remove_agent("live@demo")


@pytest.mark.asyncio
async def test_debugger_service_run_tool_action_executes_tool_and_emits_events(tmp_path):
    store = EventStore()
    contexts = AgentContextRegistry()
    contexts.register(
        AgentContextSnapshot(
            agent_id="worker@demo",
            session_id="worker-session",
            root_agent_id="worker@demo",
            prompt="do work",
        )
    )
    service = SwarmDebuggerService(
        event_store=store,
        context_registry=contexts,
        cwd=tmp_path,
        tool_registry=create_default_tool_registry(),
    )

    result = await service.run_agent_action(
        agent_id="worker@demo",
        action="run_tool",
        params={"tool_name": "brief", "tool_input": {"text": "hello world", "max_chars": 20}},
    )

    assert result["tool_name"] == "brief"
    assert result["output"] == "hello world"
    event_types = [event.event_type for event in store.events_for_agent("worker@demo")]
    assert "tool_called" in event_types
    assert "tool_completed" in event_types


@pytest.mark.asyncio
async def test_debugger_service_live_spawn_switches_active_source_to_live(monkeypatch):
    live_store = EventStore()
    live_store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="live@demo",
            root_agent_id="live@demo",
            session_id="live-session",
            payload={"name": "live", "team": "demo", "backend_type": "subprocess", "task_id": "task-live"},
        )
    )
    live_contexts = AgentContextRegistry()
    live_contexts.register(
        AgentContextSnapshot(
            agent_id="live@demo",
            session_id="live-session",
            prompt="live",
        )
    )
    service = SwarmDebuggerService(event_store=live_store, context_registry=live_contexts)
    service.run_scenario("single_child")

    async def _fake_execute(self, arguments, context):
        return ToolResult(output="Spawned persistent agent smoke@default (task_id=t1)")

    monkeypatch.setattr("openharness.swarm.debugger.AgentTool.execute", _fake_execute)
    monkeypatch.setattr(
        "openharness.swarm.topology_reader.load_persisted_task_record",
        lambda task_id: TaskRecord(
            id=task_id,
            type="in_process_teammate",
            status="running",
            description="demo",
            cwd=".",
            output_file=Path(".") / f"{task_id}.log",
            command="python -m openharness --backend-only",
        ),
    )

    result = await service.spawn_agent(agent_id="smoke", prompt="hello", mode="live")

    assert result["mode"] == "live"
    assert service.snapshot()["active_source"] == "live"
    assert service.snapshot()["tree"]["roots"] == ["live@demo"]


@pytest.mark.asyncio
async def test_debugger_service_live_spawn_without_parent_bootstraps_main(monkeypatch):
    store = EventStore()
    contexts = AgentContextRegistry()
    service = SwarmDebuggerService(event_store=store, context_registry=contexts)
    calls: list[tuple[str, dict[str, object]]] = []

    async def _fake_execute(self, arguments, context):
        calls.append((str(arguments.subagent_type), dict(context.metadata)))
        agent_id = f"{arguments.subagent_type}@default"
        parent_agent_id = context.metadata.get("swarm_agent_id")
        root_agent_id = context.metadata.get("swarm_root_agent_id") or agent_id
        lineage_path = tuple(context.metadata.get("swarm_lineage_path") or (agent_id,))
        contexts.register(
            AgentContextSnapshot(
                agent_id=agent_id,
                session_id=agent_id,
                parent_agent_id=str(parent_agent_id) if parent_agent_id is not None else None,
                root_agent_id=str(root_agent_id),
                lineage_path=lineage_path,
                prompt=arguments.prompt,
            )
        )
        store.append(
            new_swarm_event(
                "agent_spawned",
                agent_id=agent_id,
                parent_agent_id=str(parent_agent_id) if parent_agent_id is not None else None,
                root_agent_id=str(root_agent_id),
                session_id=agent_id,
                payload={
                    "name": str(arguments.subagent_type),
                    "team": "default",
                    "backend_type": "subprocess",
                    "spawn_mode": "persistent",
                    "task_id": f"task-{arguments.subagent_type}",
                    "lineage_path": list(lineage_path),
                },
            )
        )
        store.append(
            new_swarm_event(
                "agent_became_running",
                agent_id=agent_id,
                parent_agent_id=str(parent_agent_id) if parent_agent_id is not None else None,
                root_agent_id=str(root_agent_id),
                session_id=agent_id,
            )
        )
        return ToolResult(output=f"Spawned persistent agent {agent_id} (task_id=task-{arguments.subagent_type})")

    monkeypatch.setattr("openharness.swarm.debugger.AgentTool.execute", _fake_execute)

    result = await service.spawn_agent(agent_id="worker", prompt="hello", mode="live")

    assert result["mode"] == "live"
    assert [name for name, _ in calls] == ["main", "worker"]
    assert calls[1][1]["swarm_agent_id"] == "main@default"
    assert calls[1][1]["swarm_root_agent_id"] == "main@default"
    assert service.snapshot()["tree"]["roots"] == ["main@default"]
    assert service.snapshot()["tree"]["nodes"]["main@default"]["children"] == ["worker@default"]


def test_snapshot_includes_monotonic_snapshot_revision():
    svc = create_default_swarm_debugger_service()
    first = svc.snapshot()
    second = svc.snapshot()
    assert "snapshot_revision" in first
    assert first["snapshot_revision"] < second["snapshot_revision"]


def test_playback_does_not_advance_live_snapshot_revision():
    svc = create_default_swarm_debugger_service()
    live = svc.snapshot()
    playback = svc.playback()
    live_after = svc.snapshot()

    assert playback["snapshot_revision"] == live["snapshot_revision"]
    assert live_after["snapshot_revision"] == live["snapshot_revision"] + 1


def test_agent_feed_is_capped_but_keeps_prompt():
    store = EventStore()
    contexts = AgentContextRegistry()
    contexts.register(
        AgentContextSnapshot(
            agent_id="worker@demo",
            session_id="worker-session",
            prompt="Keep this prompt",
        )
    )
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="worker@demo",
            root_agent_id="worker@demo",
            session_id="worker-session",
            payload={"name": "worker", "team": "demo"},
        )
    )
    for index in range(100):
        store.append(
            new_swarm_event(
                "assistant_message",
                agent_id="worker@demo",
                root_agent_id="worker@demo",
                session_id="worker-session",
                payload={"text": f"message-{index}", "has_tool_uses": False},
            )
        )

    feed = SwarmDebuggerService(event_store=store, context_registry=contexts).snapshot()["agents"]["worker@demo"]["feed"]

    assert feed[0]["item_type"] == "prompt"
    assert feed[0]["text"] == "Keep this prompt"
    assert len(feed) == 81
    assert feed[-1]["text"] == "message-99"


@pytest.mark.asyncio
async def test_scenario_send_message_routes_to_scenario_store_not_global():
    """Preset scenarios use _scenario_* registries; routing must not write only to global EventStore."""
    get_event_store().clear()
    svc = create_default_swarm_debugger_service()
    svc.run_scenario("single_child")
    global_before = len(get_event_store().all_events())
    await svc.send_message("main", "user ping")
    assert len(get_event_store().all_events()) == global_before
    snap = svc.snapshot()
    main_types = {e["event_type"] for e in snap["timeline"] if e.get("agent_id") == "main"}
    assert "message_send_requested" in main_types
    assert "message_routed" in main_types
    assert "message_delivered" in main_types
    assert "manual_message_injected" in main_types


@pytest.mark.asyncio
async def test_scenario_send_message_resolves_main_default_id():
    get_event_store().clear()
    svc = create_default_swarm_debugger_service()
    svc.run_scenario("single_child")
    await svc.send_message("main@default", "x")
    snap = svc.snapshot()
    assert any(
        e["event_type"] == "manual_message_injected" and e.get("agent_id") == "main"
        for e in snap["timeline"]
    )


@pytest.mark.asyncio
async def test_spawn_agent_rejects_empty_agent_id():
    service = SwarmDebuggerService(event_store=EventStore(), context_registry=AgentContextRegistry())
    with pytest.raises(ValueError, match="agent_id is required"):
        await service.spawn_agent(agent_id="   ", prompt="x", mode="synthetic")


def test_canonical_agent_id_rejects_missing_name_before_at():
    with pytest.raises(ValueError, match="name before '@'"):
        SwarmDebuggerService._canonical_agent_id("@default")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("worker", "worker@default"),
        ("worker@demo", "worker@demo"),
        (" Worker@Demo ", "Worker@Demo"),
    ],
)
def test_canonical_agent_id_normalizes(raw, expected):
    assert SwarmDebuggerService._canonical_agent_id(raw) == expected
