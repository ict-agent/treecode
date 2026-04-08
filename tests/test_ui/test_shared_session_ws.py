"""Integration tests for SwarmConsoleWsServer + SessionHost (unified web console)."""

from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from openharness.session_host_registry import set_active_session_host
from openharness.swarm.console_ws import SwarmConsoleWsServer
from openharness.tasks import get_task_manager
from openharness.ui.session_host import SessionHost, SessionHostConfig

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
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))

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

        async def _recv_two() -> tuple[dict, dict]:
            async with websockets.connect(url) as conn:
                raw1 = await asyncio.wait_for(conn.recv(), timeout=10)
                raw2 = await asyncio.wait_for(conn.recv(), timeout=10)
                return json.loads(raw1), json.loads(raw2)

        first, second = await _recv_two()
        assert first["type"] == "snapshot"
        assert second["type"] == "repl_event"
        assert second["payload"]["event"]["type"] == "session_resync"
        assert "transcript" in second["payload"]["event"]
    finally:
        await ws_server.stop()
        set_active_session_host(None)
        if host.bundle is not None:
            from openharness.ui.runtime import close_runtime

            await close_runtime(host.bundle)


@pytest.mark.asyncio
async def test_session_resync_excludes_finished_agent_tasks_from_agent_count(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))

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
            from openharness.ui.runtime import close_runtime

            await close_runtime(host.bundle)
