"""agent-debug CLI integration (requires ANTHROPIC_API_KEY — see tests/real_api/conftest.py)."""

import subprocess
import json
import shutil
from pathlib import Path

import pytest

# Subprocess + FIFO lifecycle; default 10s pytest-timeout is too tight.
pytestmark = pytest.mark.timeout(120)

# Path to the .treecode/sessions directory
SESSIONS_ROOT = Path(".treecode/sessions")


def run_agent_debug(*args):
    """Helper to run treecode agent-debug commands."""
    cmd = ["uv", "run", "treecode", "agent-debug"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def test_agent_debug_lifecycle():
    session_id = "pytest-debug-session"
    session_dir = SESSIONS_ROOT / session_id
    
    # Ensure clean state
    if session_dir.exists():
        shutil.rmtree(session_dir)
    
    try:
        # 1. Start session
        start_res = run_agent_debug("start", session_id)
        assert start_res.returncode == 0
        assert f"Started agent debug session: {session_id}" in start_res.stdout
        
        # Verify files created
        assert session_dir.exists()
        assert (session_dir / "input").is_fifo()
        assert (session_dir / "output").exists()
        assert (session_dir / "state.json").exists()
        
        # 2. Send a command (slash command to set mode)
        # Using /permissions set full_auto to avoid blocking
        send_res = run_agent_debug("send", session_id, "/permissions set full_auto")
        assert send_res.returncode == 0
        assert "transcript_item" in send_res.stdout
        assert "Permission mode set to Auto" in send_res.stdout
        
        # 3. Send a plain text message
        send_msg_res = run_agent_debug("send", session_id, "hello")
        assert send_msg_res.returncode == 0
        assert "assistant_complete" in send_msg_res.stdout
        
        # Verify pretty_output.txt exists
        pretty_out = session_dir / "pretty_output.txt"
        assert pretty_out.exists()
        content = pretty_out.read_text()
        assert "[USER]" in content
        assert "hello" in content
        assert "[ASSISTANT]" in content
        
        # 4. Stop session
        stop_res = run_agent_debug("stop", session_id)
        assert stop_res.returncode == 0
        assert f"Stopped session '{session_id}'" in stop_res.stdout
        
        # Verify state changed to closed or process ended
        state = json.loads((session_dir / "state.json").read_text())
        assert state["status"] == "closed"
        
    finally:
        # Cleanup
        if session_dir.exists():
            shutil.rmtree(session_dir)

def test_agent_debug_verbose():
    session_id = "pytest-verbose-session"
    session_dir = SESSIONS_ROOT / session_id
    
    if session_dir.exists():
        shutil.rmtree(session_dir)
        
    try:
        # Start with --verbose
        start_res = run_agent_debug("start", session_id, "--verbose")
        assert start_res.returncode == 0
        
        # Send message
        run_agent_debug("send", session_id, "ping")
        
        # Verify verbose log exists
        verbose_log = session_dir / "pretty_output_verbose.txt"
        assert verbose_log.exists()
        content = verbose_log.read_text()
        assert "[LLM API INVOCATION]" in content
        assert "New Messages" in content
        
        run_agent_debug("stop", session_id)
    finally:
        if session_dir.exists():
            shutil.rmtree(session_dir)
