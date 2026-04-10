"""Integration tests for SwarmConsoleWsServer + SessionHost (unified web console)."""

from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from treecode.session_host_registry import set_active_session_host
from treecode.swarm.console_ws import SwarmConsoleWsServer
from treecode.tasks import get_task_manager
from treecode.ui.session_host import SessionHost, SessionHostConfig

from tests.test_ui.test_react_backend import StaticApiClient


async def _wait_for_task_terminal(task_id: str, *, timeout: float = 5.0) -> None:
    manager = get_task_manager()
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        task = manager.get_task(task_id)
        if task is not None and task.status in {"completed", "failed", "killed"}:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"Task {task_id} did not reach a terminal state within {timeout}s")


@pytest.mark.asyncio
async def test_websocket_client_receives_snapshot_then_session_resync(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TREECODE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))

    config = SessionHostConfig(api_client=StaticApiClient("ws-test"), enable_shared_web=False)
    host = SessionHost(config)
    await host.start()

    assert host.debugger is not None
    ws_server = SwarmConsoleWsServer(
        service=host.debugger,
        host="127.0.0.1",
        port=0,
        session_host=host,
    )
    await ws_server.start()
    url = ws_server.ws_url

    try:

        async def _recv_handshake() -> tuple[dict, dict, dict]:
            async with websockets.connect(url) as conn:
                raw1 = await asyncio.wait_for(conn.recv(), timeout=10)
                raw2 = await asyncio.wait_for(conn.recv(), timeout=10)
                raw3 = await asyncio.wait_for(conn.recv(), timeout=10)
                return json.loads(raw1), json.loads(raw2), json.loads(raw3)

        first, second, third = await _recv_handshake()
        assert first["type"] == "snapshot"
        assert second["type"] == "repl_input_history"
        assert isinstance(second.get("payload", {}).get("lines"), list)
        assert third["type"] == "repl_event"
        assert third["payload"]["event"]["type"] == "session_resync"
        assert "transcript" in third["payload"]["event"]
    finally:
        await ws_server.stop()
        set_active_session_host(None)
        if host.bundle is not None:
            from treecode.ui.runtime import close_runtime

            await close_runtime(host.bundle)


@pytest.mark.asyncio
async def test_session_resync_excludes_finished_agent_tasks_from_agent_count(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TREECODE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("TREECODE_DATA_DIR", str(tmp_path / "data"))

    config = SessionHostConfig(api_client=StaticApiClient("ws-test"), enable_shared_web=False)
    host = SessionHost(config)
    await host.start()

    manager = get_task_manager()
    task = await manager.create_shell_task(
        command="python -c \"print('done')\"",
        description="short-lived agent",
        cwd=tmp_path,
        task_type="local_agent",
    )
    await _wait_for_task_terminal(task.id)

    try:
        event = host.build_session_resync_event()
        assert event.agent_tasks_total == 0
        assert event.tasks == []
    finally:
        set_active_session_host(None)
        if host.bundle is not None:
            from treecode.ui.runtime import close_runtime

            await close_runtime(host.bundle)


@pytest.mark.asyncio
async def test_session_host_shutdown_stops_owned_persistent_agents_in_leaf_first_order():
    host = SessionHost(SessionHostConfig(api_client=StaticApiClient("ws-test"), enable_shared_web=False))

    class _Bundle:
        cwd = "/tmp/demo"
        session_id = "sess-main"

    stopped: list[str] = []

    class _Debugger:
        def snapshot(self):
            return {
                "tree": {
                    "roots": ["main@default"],
                    "nodes": {
                        "main@default": {
                            "lineage_path": ["main@default"],
                            "children": ["A@default"],
                            "spawn_mode": "interactive",
                        },
                        "A@default": {
                            "lineage_path": ["main@default", "A@default"],
                            "children": ["A1@default"],
                            "spawn_mode": "persistent",
                        },
                        "A1@default": {
                            "lineage_path": ["main@default", "A@default", "A1@default"],
                            "children": [],
                            "spawn_mode": "persistent",
                        },
                    },
                }
            }

        async def stop_agent(self, agent_id: str) -> bool:
            stopped.append(agent_id)
            return True

    host._bundle = _Bundle()  # type: ignore[assignment]
    host._debugger = _Debugger()  # type: ignore[assignment]

    await host._shutdown_owned_persistent_agents()

    assert stopped == ["A1@default", "A@default"]
