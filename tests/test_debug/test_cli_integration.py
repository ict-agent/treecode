"""Integration tests for debug output functionality."""

import subprocess
import tempfile
from pathlib import Path

def test_debug_output_flag_print_mode():
    """Test that --debug-output flag works in print mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        debug_log = Path(tmpdir) / "debug.log"
        
        result = subprocess.run(
            [
                "uv", "run", "oh",
                "--debug-output", str(debug_log),
                "--permission-mode", "full_auto",
                "-p", "What is 2 + 2?"
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        # Command should succeed
        assert result.returncode == 0, f"Command failed: {result.stderr}"
        
        # Debug log should exist
        assert debug_log.exists(), "Debug log was not created"
        
        content = debug_log.read_text()
        
        # Should contain some debug output
        assert len(content) > 0, "Debug log is empty"
        
        print(f"Debug log content:\n{content}")
        print("\nTest passed!")


def test_debug_output_flag_with_tool_use():
    """Test debug output with a command that uses tools."""
    with tempfile.TemporaryDirectory() as tmpdir:
        debug_log = Path(tmpdir) / "debug.log"
        
        result = subprocess.run(
            [
                "uv", "run", "oh",
                "--debug-output", str(debug_log),
                "--permission-mode", "full_auto",
                "-p", "List files in current directory"
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        # Command should succeed
        assert result.returncode == 0, f"Command failed: {result.stderr}"
        
        # Debug log should exist and contain tool-related entries
        assert debug_log.exists(), "Debug log was not created"
        
        content = debug_log.read_text()
        
        # Should contain tool call markers
        assert "[TOOL CALL:" in content or "[TOOL RESPONSE]" in content, \
            f"Expected tool call in debug log:\n{content}"
        
        print(f"Debug log content:\n{content}")
        print("\nTest passed!")

