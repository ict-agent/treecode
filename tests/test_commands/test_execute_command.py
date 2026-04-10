"""Tests for /execute command helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from treecode.commands.registry import CommandContext, create_default_command_registry
from treecode.engine.query_engine import QueryEngine
from treecode.permissions import PermissionChecker
from treecode.config.settings import load_settings
from treecode.tools import create_default_tool_registry
from treecode.commands.execute_script import ExecutableInputLine, load_execute_lines


def test_load_execute_lines_filters_blank_and_comment_lines(tmp_path: Path):
    script = tmp_path / "setup.txt"
    script.write_text(
        "\n"
        "# initialize topology\n"
        "   # indented comment\n"
        "/spawn worker A \"node A\"\n"
        "\n"
        "list files in current directory\n",
        encoding="utf-8",
    )

    lines = load_execute_lines(script, cwd=tmp_path)

    assert lines == [
        ExecutableInputLine(line_no=4, raw_text="/spawn worker A \"node A\"", input_text="/spawn worker A \"node A\""),
        ExecutableInputLine(line_no=6, raw_text="list files in current directory", input_text="list files in current directory"),
    ]


def test_load_execute_lines_resolves_relative_paths_from_cwd(tmp_path: Path):
    script = tmp_path / "scripts" / "bootstrap.txt"
    script.parent.mkdir(parents=True)
    script.write_text("/spawn worker A \"node A\"\n", encoding="utf-8")

    lines = load_execute_lines(Path("scripts/bootstrap.txt"), cwd=tmp_path)

    assert len(lines) == 1
    assert lines[0].line_no == 1
    assert lines[0].input_text == '/spawn worker A "node A"'


def test_load_execute_lines_raises_for_missing_file(tmp_path: Path):
    missing = tmp_path / "missing.txt"

    try:
        load_execute_lines(missing, cwd=tmp_path)
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError")


def test_checked_in_gather_handshake_bootstrap_fixture_loads():
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "execute" / "gather_handshake_bootstrap.txt"
    )

    lines = load_execute_lines(fixture_path, cwd=fixture_path.parent)

    assert lines[0].input_text.startswith("/spawn worker A ")
    assert lines[-1].input_text.startswith("/gather --spec gather_handshake ")


class FakeApiClient:
    async def stream_message(self, request):
        del request
        raise AssertionError("stream_message should not be called in execute command tests")


def _make_context(tmp_path: Path, *, replay_line):
    tool_registry = create_default_tool_registry()
    engine = QueryEngine(
        api_client=FakeApiClient(),
        tool_registry=tool_registry,
        permission_checker=PermissionChecker(load_settings().permission),
        cwd=tmp_path,
        model="claude-test",
        system_prompt="system",
    )
    return CommandContext(
        engine=engine,
        cwd=str(tmp_path),
        tool_registry=tool_registry,
        replay_input_line=replay_line,
    )


@pytest.mark.asyncio
async def test_execute_command_replays_lines_in_order_and_ignores_comments(tmp_path: Path):
    script = tmp_path / "setup.txt"
    script.write_text(
        "# bootstrap\n"
        "/spawn worker A \"node A\"\n"
        "\n"
        "/spawn worker B \"node B\"\n",
        encoding="utf-8",
    )
    replayed: list[str] = []

    async def replay_line(line: str):
        replayed.append(line)
        return {"ok": True, "should_continue": True, "error": None}

    registry = create_default_command_registry()
    command, args = registry.lookup(f"/execute {script}")

    result = await command.handler(args, _make_context(tmp_path, replay_line=replay_line))

    assert replayed == [
        '/spawn worker A "node A"',
        '/spawn worker B "node B"',
    ]
    assert "Executed 2 line(s)" in result.message


@pytest.mark.asyncio
async def test_execute_command_stops_on_first_failed_line(tmp_path: Path):
    script = tmp_path / "setup.txt"
    script.write_text(
        "/spawn worker A \"node A\"\n"
        "/spawn worker B \"node B\"\n"
        "/spawn worker C \"node C\"\n",
        encoding="utf-8",
    )
    replayed: list[str] = []

    async def replay_line(line: str):
        replayed.append(line)
        if "B" in line:
            return {"ok": False, "should_continue": True, "error": "Unknown parent agent"}
        return {"ok": True, "should_continue": True, "error": None}

    registry = create_default_command_registry()
    command, args = registry.lookup(f"/execute {script}")

    result = await command.handler(args, _make_context(tmp_path, replay_line=replay_line))

    assert replayed == [
        '/spawn worker A "node A"',
        '/spawn worker B "node B"',
    ]
    assert "line 2" in result.message
    assert "Unknown parent agent" in result.message
