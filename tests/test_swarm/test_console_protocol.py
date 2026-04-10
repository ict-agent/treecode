"""Tests for swarm console WebSocket protocol models."""

from __future__ import annotations

from treecode.swarm.console_protocol import ConsoleClientMessage, ConsoleServerMessage


def test_console_client_message_parses_command_payload():
    message = ConsoleClientMessage.model_validate(
        {
            "type": "command",
            "command": "run_scenario",
            "payload": {"name": "two_level_fanout"},
        }
    )

    assert message.type == "command"
    assert message.command == "run_scenario"
    assert message.payload == {"name": "two_level_fanout"}


def test_console_client_message_parses_unified_agent_action():
    message = ConsoleClientMessage.model_validate(
        {
            "type": "command",
            "command": "agent_action",
            "payload": {
                "agent_id": "sub1",
                "action": "spawn_child",
                "params": {"child_agent_id": "A", "prompt": "Do work"},
            },
        }
    )

    assert message.command == "agent_action"
    assert message.payload["action"] == "spawn_child"


def test_console_server_message_serializes_snapshot_payload():
    message = ConsoleServerMessage(
        type="snapshot",
        payload={"overview": {"agent_count": 4}},
    )

    assert message.model_dump()["type"] == "snapshot"
    assert message.model_dump()["payload"]["overview"]["agent_count"] == 4
