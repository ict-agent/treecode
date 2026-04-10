"""Tests for the swarm console WebSocket server."""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.client import connect

from treecode.swarm.console_ws import SwarmConsoleWsServer
from treecode.swarm.context_registry import AgentContextRegistry
from treecode.swarm.debugger import SwarmDebuggerService
from treecode.swarm.event_store import EventStore
from treecode.swarm.events import new_swarm_event
from treecode.tasks.types import TaskRecord


async def _recv_console_connect_handshake(websocket) -> dict:
    """On connect the server sends snapshot then repl_input_history (shared with Ink TUI)."""
    initial = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
    assert initial["type"] == "snapshot"
    hist = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
    assert hist["type"] == "repl_input_history"
    assert isinstance(hist.get("payload", {}).get("lines"), list)
    return initial


@pytest.mark.asyncio
async def test_console_ws_server_sends_snapshot_and_handles_run_scenario():
    service = SwarmDebuggerService(event_store=EventStore(), context_registry=AgentContextRegistry())
    server = SwarmConsoleWsServer(service=service, host="127.0.0.1", port=0)
    await server.start()
    try:
        async with connect(server.ws_url) as websocket:
            await _recv_console_connect_handshake(websocket)

            await websocket.send(
                json.dumps(
                    {
                        "type": "command",
                        "command": "run_scenario",
                        "payload": {"name": "two_level_fanout"},
                    }
                )
            )

            ack = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            updated = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))

            assert ack["type"] == "ack"
            assert ack["payload"]["scenario"] == "two_level_fanout"
            assert updated["type"] == "snapshot"
            assert updated["payload"]["tree"]["roots"] == ["main"]
            assert updated["payload"]["agents"]["main"]["synthetic"] is True
            assert updated["payload"]["agents"]["main"]["feed"][0]["item_type"] == "prompt"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_console_ws_server_bootstraps_live_main_in_initial_snapshot(monkeypatch):
    store = EventStore()
    contexts = AgentContextRegistry()
    service = SwarmDebuggerService(
        event_store=store,
        context_registry=contexts,
        auto_bootstrap_live_main=True,
    )
    bootstrapped: list[str] = []

    async def _ensure_live_main():
        bootstrapped.append("main@default")
        contexts.register(
            __import__("treecode.swarm.context_registry", fromlist=["AgentContextSnapshot"]).AgentContextSnapshot(
                agent_id="main@default",
                session_id="main@default",
                root_agent_id="main@default",
                lineage_path=("main@default",),
                prompt="main",
            )
        )
        store.append(
            new_swarm_event(
                "agent_spawned",
                agent_id="main@default",
                root_agent_id="main@default",
                session_id="main@default",
                payload={
                    "name": "main",
                    "team": "default",
                    "backend_type": "subprocess",
                    "spawn_mode": "persistent",
                    "task_id": "task-main",
                    "lineage_path": ["main@default"],
                },
            )
        )
        store.append(
            new_swarm_event(
                "agent_became_running",
                agent_id="main@default",
                root_agent_id="main@default",
                session_id="main@default",
            )
        )
        return "main@default"

    monkeypatch.setattr(service, "maybe_ensure_live_main", _ensure_live_main)
    server = SwarmConsoleWsServer(service=service, host="127.0.0.1", port=0)
    await server.start()
    try:
        async with connect(server.ws_url) as websocket:
            initial = await _recv_console_connect_handshake(websocket)
            assert bootstrapped == ["main@default"]
            assert initial["payload"]["tree"]["roots"] == ["main@default"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_console_ws_server_handles_unified_agent_action():
    service = SwarmDebuggerService(event_store=EventStore(), context_registry=AgentContextRegistry())
    service.run_scenario("single_child")
    server = SwarmConsoleWsServer(service=service, host="127.0.0.1", port=0)
    await server.start()
    try:
        async with connect(server.ws_url) as websocket:
            await _recv_console_connect_handshake(websocket)

            await websocket.send(
                json.dumps(
                    {
                        "type": "command",
                        "command": "agent_action",
                        "payload": {
                            "agent_id": "sub1",
                            "action": "inspect",
                            "params": {},
                        },
                    }
                )
            )

            ack = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            assert ack["type"] == "ack"
            assert ack["payload"]["agent_id"] == "sub1"
            assert ack["payload"]["context"]["prompt"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_console_ws_server_pushes_snapshot_when_background_events_change():
    store = EventStore()
    store.append(
        new_swarm_event(
            "agent_spawned",
            agent_id="main@default",
            root_agent_id="main@default",
            session_id="main@default",
            payload={"name": "main", "team": "default", "backend_type": "subprocess", "task_id": "task-main"},
        )
    )
    service = SwarmDebuggerService(event_store=store, context_registry=AgentContextRegistry())
    server = SwarmConsoleWsServer(service=service, host="127.0.0.1", port=0)
    await server.start()
    try:
        async with connect(server.ws_url) as websocket:
            await _recv_console_connect_handshake(websocket)

            store.append(
                new_swarm_event(
                    "assistant_message",
                    agent_id="main@default",
                    root_agent_id="main@default",
                    session_id="main@default",
                    payload={"text": "background reply", "has_tool_uses": False},
                )
            )

            pushed = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            assert pushed["type"] == "snapshot"
            feed = pushed["payload"]["agents"]["main@default"]["feed"]
            assert any(item.get("item_type") == "assistant" and item.get("text") == "background reply" for item in feed)
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_console_ws_server_handles_run_tool_agent_action(tmp_path):
    service = SwarmDebuggerService(
        event_store=EventStore(),
        context_registry=AgentContextRegistry(),
        cwd=tmp_path,
    )
    service.run_scenario("single_child")
    server = SwarmConsoleWsServer(service=service, host="127.0.0.1", port=0)
    await server.start()
    try:
        async with connect(server.ws_url) as websocket:
            await _recv_console_connect_handshake(websocket)

            await websocket.send(
                json.dumps(
                    {
                        "type": "command",
                        "command": "agent_action",
                        "payload": {
                            "agent_id": "sub1",
                            "action": "run_tool",
                            "params": {
                                "tool_name": "brief",
                                "tool_input": {"text": "hello world", "max_chars": 20},
                            },
                        },
                    }
                )
            )

            ack = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            assert ack["type"] == "ack"
            assert ack["payload"]["tool_name"] == "brief"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_console_ws_server_can_switch_active_source():
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
    service = SwarmDebuggerService(event_store=live_store, context_registry=AgentContextRegistry())
    service.run_scenario("single_child")
    server = SwarmConsoleWsServer(service=service, host="127.0.0.1", port=0)
    await server.start()
    try:
        async with connect(server.ws_url) as websocket:
            await _recv_console_connect_handshake(websocket)
            await websocket.send(
                json.dumps(
                    {
                        "type": "command",
                        "command": "set_active_source",
                        "payload": {"source": "live"},
                    }
                )
            )
            ack = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            snapshot = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            assert ack["payload"]["active_source"] == "live"
            assert snapshot["payload"]["tree"]["roots"] == ["live@demo"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_console_ws_server_can_switch_topology_view(monkeypatch, tmp_path):
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

    def _load(task_id: str):
        status = "running" if task_id == "task-worker" else "completed"
        return TaskRecord(
            id=task_id,
            type="in_process_teammate",
            status=status,
            description="demo",
            cwd=str(tmp_path),
            output_file=tmp_path / f"{task_id}.log",
            command="python -m treecode --backend-only",
        )

    monkeypatch.setattr("treecode.swarm.topology_reader.load_persisted_task_record", _load)
    service = SwarmDebuggerService(
        event_store=live_store,
        context_registry=AgentContextRegistry(),
        reconcile_live_runtime=True,
    )
    server = SwarmConsoleWsServer(service=service, host="127.0.0.1", port=0)
    await server.start()
    try:
        async with connect(server.ws_url) as websocket:
            initial = await _recv_console_connect_handshake(websocket)
            assert "stale@demo" not in initial["payload"]["agents"]

            await websocket.send(
                json.dumps(
                    {
                        "type": "command",
                        "command": "set_topology_view",
                        "payload": {"view": "raw_events"},
                    }
                )
            )
            ack = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            snapshot = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            assert ack["type"] == "ack"
            assert ack["payload"]["topology_view"] == "raw_events"
            assert snapshot["payload"]["topology_view"] == "raw_events"
            assert "stale@demo" in snapshot["payload"]["agents"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_console_ws_server_returns_archives_and_compare_results(tmp_path):
    service = SwarmDebuggerService(
        event_store=EventStore(),
        context_registry=AgentContextRegistry(),
        archive_dir=tmp_path,
    )
    service.run_scenario("single_child")
    first = service.archive_current_run(label="first")
    service.run_scenario("two_level_fanout")
    second = service.archive_current_run(label="second")

    server = SwarmConsoleWsServer(service=service, host="127.0.0.1", port=0)
    await server.start()
    try:
        async with connect(server.ws_url) as websocket:
            await _recv_console_connect_handshake(websocket)

            await websocket.send(json.dumps({"type": "command", "command": "list_archives", "payload": {}}))
            archives = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            assert archives["type"] == "archives"
            assert len(archives["payload"]["archives"]) == 2

            await websocket.send(
                json.dumps(
                    {
                        "type": "command",
                        "command": "compare_runs",
                        "payload": {"left_run_id": first["run_id"], "right_run_id": second["run_id"]},
                    }
                )
            )
            comparison = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            assert comparison["type"] == "compare_result"
            assert comparison["payload"]["left_run_id"] == first["run_id"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_console_ws_server_rejects_invalid_run_ids(tmp_path):
    service = SwarmDebuggerService(
        event_store=EventStore(),
        context_registry=AgentContextRegistry(),
        archive_dir=tmp_path,
    )
    service.run_scenario("single_child")
    service.archive_current_run(label="first")

    server = SwarmConsoleWsServer(service=service, host="127.0.0.1", port=0)
    await server.start()
    try:
        async with connect(server.ws_url) as websocket:
            await _recv_console_connect_handshake(websocket)
            await websocket.send(
                json.dumps(
                    {
                        "type": "command",
                        "command": "compare_runs",
                        "payload": {"left_run_id": "../oops", "right_run_id": "../oops"},
                    }
                )
            )
            error = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            assert error["type"] == "error"
            assert "Invalid run_id" in error["message"]
    finally:
        await server.stop()
