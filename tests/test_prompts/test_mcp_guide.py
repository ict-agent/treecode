"""Tests for MCP tools guide in the system prompt."""

from __future__ import annotations

from treecode.mcp.types import McpConnectionStatus, McpToolInfo
from treecode.prompts.context import _build_mcp_tools_guide


class FakeMcpManager:
    """Minimal stand-in that exposes list_statuses()."""

    def __init__(self, statuses: list[McpConnectionStatus]) -> None:
        self._statuses = statuses

    def list_statuses(self) -> list[McpConnectionStatus]:
        return self._statuses


def _make_status(
    name: str = "test-server",
    tools: list[str] | None = None,
    instructions: str = "",
) -> McpConnectionStatus:
    tool_infos = [
        McpToolInfo(server_name=name, name=t, description="", input_schema={})
        for t in (tools or ["some_tool"])
    ]
    return McpConnectionStatus(
        name=name,
        state="connected",
        tools=tool_infos,
        instructions=instructions,
    )


def test_no_manager_returns_none():
    assert _build_mcp_tools_guide(None) is None


def test_no_connected_servers_returns_none():
    status = McpConnectionStatus(name="s", state="failed")
    manager = FakeMcpManager([status])
    assert _build_mcp_tools_guide(manager) is None


def test_server_instructions_included():
    status = _make_status(instructions="Use find_symbol before reading files.")
    manager = FakeMcpManager([status])
    guide = _build_mcp_tools_guide(manager)
    assert "Use find_symbol before reading files." in guide
    assert "test-server" in guide


def test_fallback_semantic_hints_when_no_instructions():
    status = _make_status(tools=["find_symbol", "get_symbols_overview", "find_referencing_symbols"])
    manager = FakeMcpManager([status])
    guide = _build_mcp_tools_guide(manager)
    assert "semantic code analysis" in guide
    assert "`find_symbol`" in guide


def test_server_instructions_suppress_fallback_hints():
    status = _make_status(
        tools=["find_symbol", "get_symbols_overview"],
        instructions="Custom server guidance here.",
    )
    manager = FakeMcpManager([status])
    guide = _build_mcp_tools_guide(manager)
    assert "Custom server guidance here." in guide
    assert "semantic code analysis" not in guide


def test_tool_list_always_present():
    status = _make_status(tools=["tool_a", "tool_b"], instructions="Some guide.")
    manager = FakeMcpManager([status])
    guide = _build_mcp_tools_guide(manager)
    assert "`tool_a`" in guide
    assert "`tool_b`" in guide
