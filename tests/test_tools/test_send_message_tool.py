"""Tests for swarm-aware send_message tool routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from openharness.swarm.event_store import get_event_store
from openharness.tools.base import ToolExecutionContext
from openharness.tools.send_message_tool import SendMessageTool, SendMessageToolInput


@pytest.mark.asyncio
async def test_send_message_tool_uses_swarm_sender_identity(tmp_path: Path, monkeypatch):
    captured = {}
    store = get_event_store()
    store.clear()

    class FakeExecutor:
        async def send_message(self, agent_id, message):
            captured["agent_id"] = agent_id
            captured["message"] = message

    class FakeRegistry:
        def get_executor(self, backend_type=None):
            assert backend_type == "in_process"
            return FakeExecutor()

    monkeypatch.setattr("openharness.tools.send_message_tool.get_backend_registry", lambda: FakeRegistry())
    tool = SendMessageTool()
    result = await tool.execute(
        SendMessageToolInput(task_id="worker@demo", message="do work"),
        ToolExecutionContext(
            cwd=tmp_path,
            metadata={
                "swarm_agent_id": "leader@demo",
                "swarm_root_agent_id": "leader@demo",
                "session_id": "root-session",
            },
        ),
    )

    assert result.is_error is False
    assert captured["agent_id"] == "worker@demo"
    assert captured["message"].from_agent == "leader@demo"
    assert [event.event_type for event in store.events_for_agent("worker@demo")] == [
        "message_send_requested",
        "message_routed",
        "message_delivered",
    ]
