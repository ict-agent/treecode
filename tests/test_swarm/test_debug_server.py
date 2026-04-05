"""Tests for the HTTP swarm debug server."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from openharness.swarm.context_registry import AgentContextRegistry, AgentContextSnapshot
from openharness.swarm.debug_server import SwarmDebugServer
from openharness.swarm.debugger import SwarmDebuggerService
from openharness.swarm.event_store import EventStore
from openharness.swarm.events import new_swarm_event


def _build_service() -> SwarmDebuggerService:
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
        )
    )
    return SwarmDebuggerService(event_store=store, context_registry=contexts)


def test_debug_server_serves_index_and_snapshot():
    server = SwarmDebugServer(service=_build_service(), host="127.0.0.1", port=0)
    server.start()
    try:
        index = urlopen(f"{server.base_url}/").read().decode("utf-8")
        assert "OpenHarness Swarm Debugger" in index
        assert "Overview" in index
        assert "Scenario View" in index
        assert "Agent Activity" in index
        assert "Approve" in index
        assert "Reject" in index

        payload = json.loads(urlopen(f"{server.base_url}/api/snapshot").read().decode("utf-8"))
        assert payload["tree"]["roots"] == ["leader@demo"]
        assert payload["contexts"]["worker@demo"]["prompt"] == "do work"
        assert payload["overview"]["agent_count"] == 2
    finally:
        server.stop()


def test_debug_server_handles_context_patch_post():
    service = _build_service()
    server = SwarmDebugServer(service=service, host="127.0.0.1", port=0)
    server.start()
    try:
        request = Request(
            f"{server.base_url}/api/agents/worker@demo/context-patch",
            data=json.dumps(
                {
                    "base_version": 1,
                    "patch": {"messages": ["patched"], "compacted_summary": "done"},
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        payload = json.loads(urlopen(request).read().decode("utf-8"))
        assert payload["context_version"] == 2
        assert payload["messages"] == ["patched"]
    finally:
        server.stop()


def test_debug_server_rejects_invalid_playback_limit():
    server = SwarmDebugServer(service=_build_service(), host="127.0.0.1", port=0)
    server.start()
    try:
        try:
            urlopen(f"{server.base_url}/api/playback?limit=oops")
        except Exception as exc:
            assert "HTTP Error 400" in str(exc)
        else:
            raise AssertionError("invalid playback limit should return 400")
    finally:
        server.stop()


def test_debug_server_lists_and_runs_scenarios():
    server = SwarmDebugServer(service=SwarmDebuggerService(event_store=EventStore(), context_registry=AgentContextRegistry()), host="127.0.0.1", port=0)
    server.start()
    try:
        scenarios = json.loads(urlopen(f"{server.base_url}/api/scenarios").read().decode("utf-8"))
        assert "two_level_fanout" in scenarios["scenarios"]

        request = Request(
            f"{server.base_url}/api/scenarios/two_level_fanout/run",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        payload = json.loads(urlopen(request).read().decode("utf-8"))
        assert payload["scenario"] == "two_level_fanout"

        snapshot = json.loads(urlopen(f"{server.base_url}/api/snapshot").read().decode("utf-8"))
        assert snapshot["tree"]["roots"] == ["main"]
        overview = json.loads(urlopen(f"{server.base_url}/api/overview").read().decode("utf-8"))
        assert overview["max_depth"] == 3
        scenario_view = json.loads(urlopen(f"{server.base_url}/api/scenario-view").read().decode("utf-8"))
        assert scenario_view["levels"][2]["agents"] == ["A", "B"]
    finally:
        server.stop()


def test_debug_server_resolves_approval_via_post():
    service = SwarmDebuggerService(event_store=EventStore(), context_registry=AgentContextRegistry())
    service.run_scenario("approval_on_leaf")
    server = SwarmDebugServer(service=service, host="127.0.0.1", port=0)
    server.start()
    try:
        request = Request(
            f"{server.base_url}/api/approvals/approval-on-leaf/resolve",
            data=json.dumps({"status": "approved"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        payload = json.loads(urlopen(request).read().decode("utf-8"))
        assert payload["status"] == "approved"

        snapshot = json.loads(urlopen(f"{server.base_url}/api/snapshot").read().decode("utf-8"))
        statuses = {item["correlation_id"]: item["status"] for item in snapshot["approval_queue"]}
        assert statuses["approval-on-leaf"] == "approved"
    finally:
        server.stop()
