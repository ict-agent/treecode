"""Tests for the swarm console WebSocket server."""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.client import connect

from openharness.swarm.console_ws import SwarmConsoleWsServer
from openharness.swarm.context_registry import AgentContextRegistry
from openharness.swarm.debugger import SwarmDebuggerService
from openharness.swarm.event_store import EventStore
from openharness.swarm.events import new_swarm_event


@pytest.mark.asyncio
async def test_console_ws_server_sends_snapshot_and_handles_run_scenario():
    service = SwarmDebuggerService(event_store=EventStore(), context_registry=AgentContextRegistry())
    server = SwarmConsoleWsServer(service=service, host="127.0.0.1", port=0)
    await server.start()
    try:
        async with connect(server.ws_url) as websocket:
            initial = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
            assert initial["type"] == "snapshot"

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
            _ = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))

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
            _ = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))

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
            _ = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
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
            _ = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))

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
            _ = json.loads(await asyncio.wait_for(websocket.recv(), timeout=2))
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
