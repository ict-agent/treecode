"""Unit tests for DebugLogger."""

import json
import tempfile
from pathlib import Path

import pytest

from openharness.engine.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    MaxTurnsReached,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)

from openharness.debug.logger import DebugLogger


@pytest.mark.asyncio
async def test_tool_call_logging():
    """Test that tool calls are logged correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "debug.log"
        logger = DebugLogger(log_path)
        
        # Simulate tool call
        await logger(ToolExecutionStarted(
            tool_name="bash",
            tool_input={"command": "ls -la"}
        ))
        
        await logger(ToolExecutionCompleted(
            tool_name="bash",
            output="total 123\ndrwxr-xr-x  10 user user 4096 .",
            is_error=False
        ))
        
        await logger.close()
        
        content = log_path.read_text()
        
        # Verify format matches agent-debug style
        assert "[TOOL CALL: bash]" in content
        assert '"command": "ls -la"' in content
        assert "[TOOL RESPONSE]" in content
        assert "total 123" in content


@pytest.mark.asyncio
async def test_assistant_message_logging():
    """Test that assistant messages are buffered and logged on turn complete."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "debug.log"
        logger = DebugLogger(log_path)
        
        # Simulate streaming assistant text
        await logger(AssistantTextDelta(text="The "))
        await logger(AssistantTextDelta(text="current "))
        await logger(AssistantTextDelta(text="directory "))
        await logger(AssistantTextDelta(text="contains:"))
        
        # Turn complete should flush buffer
        await logger(AssistantTurnComplete(
            message=None,  # Not used by logger
            usage=None
        ))
        
        await logger.close()
        
        content = log_path.read_text()
        
        assert "[ASSISTANT]" in content
        assert "The current directory contains:" in content


@pytest.mark.asyncio
async def test_tool_error_logging():
    """Test that tool errors are logged with ERROR tag."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "debug.log"
        logger = DebugLogger(log_path)
        
        await logger(ToolExecutionStarted(
            tool_name="file_read",
            tool_input={"file_path": "/nonexistent/file.txt"}
        ))
        
        await logger(ToolExecutionCompleted(
            tool_name="file_read",
            output="File not found: /nonexistent/file.txt",
            is_error=True
        ))
        
        await logger.close()
        
        content = log_path.read_text()
        assert "[TOOL ERROR: file_read]" in content


@pytest.mark.asyncio
async def test_max_turns_logging():
    """Test that max turns reached is logged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "debug.log"
        logger = DebugLogger(log_path)
        
        await logger(MaxTurnsReached(max_turns=8))
        await logger.close()
        
        content = log_path.read_text()
        assert "[INFO] Max turns reached (8)" in content


@pytest.mark.asyncio
async def test_complete_conversation_flow():
    """Test a full conversation flow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "debug.log"
        logger = DebugLogger(log_path)
        
        # User prompt (not a StreamEvent, typically logged separately)
        
        # Assistant responds with tool call
        await logger(AssistantTextDelta(text="I'll check the files for you."))
        
        await logger(ToolExecutionStarted(
            tool_name="bash",
            tool_input={"command": "ls -la"}
        ))
        
        await logger(ToolExecutionCompleted(
            tool_name="bash",
            output="total 123\n-rw-r--r--  1 user user 1024 test.py",
            is_error=False
        ))
        
        await logger(AssistantTurnComplete(
            message=None,
            usage=None
        ))
        
        # Second turn: assistant provides answer
        await logger(AssistantTextDelta(text="Found these files in the directory:"))
        await logger(AssistantTurnComplete(
            message=None,
            usage=None
        ))
        
        await logger.close()
        
        content = log_path.read_text()
        
        # Verify structure
        lines = content.split("\n")
        
        # Should have assistant -> tool call -> tool response -> assistant pattern
        assert "[ASSISTANT]" in content
        assert "[TOOL CALL: bash]" in content
        assert "[TOOL RESPONSE]" in content
        assert "total 123" in content
        assert "Found these files" in content

