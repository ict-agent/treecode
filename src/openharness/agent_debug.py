import io
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

AGENT_SESSIONS_ROOT = Path(".openharness/sessions")


def get_session_dir(session_id: str) -> Path:
    s = session_id.strip()
    if not s or not s.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Session ID must be alphanumeric")
    return AGENT_SESSIONS_ROOT / s


def open_stdin_fifo_for_read(path: Path | str) -> io.TextIOWrapper:
    p = str(path)
    fd = os.open(p, os.O_RDWR)
    return io.TextIOWrapper(
        io.FileIO(fd, mode="r", closefd=True),
        encoding="utf-8",
        line_buffering=True,
    )


class SessionOutputWrapper:
    def __init__(self, raw_path: Path, pretty_path: Path):
        self.raw_file = open(raw_path, "a", encoding="utf-8", buffering=1)
        self.pretty_file = open(pretty_path, "a", encoding="utf-8", buffering=1)
        self.buffer = ""

    def write(self, s: str):
        self.raw_file.write(s)
        self.buffer += s
        parts = self.buffer.split('\n')
        self.buffer = parts.pop()
        for line in parts:
            if line.startswith("OHJSON:"):
                try:
                    self._parse_pretty(json.loads(line[7:]))
                except Exception:
                    pass

    def flush(self):
        self.raw_file.flush()
        self.pretty_file.flush()

    def _parse_pretty(self, obj: dict) -> None:
        t = obj.get("type")
        item = obj.get("item") or {}
        
        if t == "transcript_item" and item.get("role") == "user":
            text = item.get("text", "").strip()
            if not text.startswith("/"):
                self.pretty_file.write(f"\n[USER]\n{text}\n")
        
        elif t == "tool_started":
            name = obj.get("tool_name", "unknown")
            inp = obj.get("tool_input", {})
            inp_str = json.dumps(inp, ensure_ascii=False, indent=2) if isinstance(inp, dict) else str(inp)
            self.pretty_file.write(f"\n[TOOL CALL: {name}]\n{inp_str}\n")
            
        elif t == "tool_completed":
            out = obj.get("output", "")
            if out:
                self.pretty_file.write(f"\n[TOOL RESPONSE]\n{str(out).strip()}\n")
            else:
                self.pretty_file.write(f"\n[TOOL RESPONSE] (Empty)\n")
            
        elif t == "assistant_complete":
            msg = obj.get("message", "").strip()
            if msg:
                self.pretty_file.write(f"\n[ASSISTANT]\n{msg}\n")


def apply_agent_session_io(session_id: str, verbose: bool = False) -> None:
    """Intercept sys.stdio via Linux FIFOs to enable daemonized input/output."""
    d = get_session_dir(session_id).resolve()
    d.mkdir(parents=True, exist_ok=True)

    stdin_path = d / "input"
    stdout_path = d / "output"
    pretty_path = d / "pretty_output.txt"
    
    verbose_path = d / "pretty_output_verbose.txt" if verbose else None

    if (d / "pretty_output.md").exists():
        (d / "pretty_output.md").unlink()
    if (d / "stderr").exists():
        (d / "stderr").unlink()

    if stdin_path.exists() and not stat.S_ISFIFO(stdin_path.stat().st_mode):
        stdin_path.unlink()
    if not stdin_path.exists():
        os.mkfifo(stdin_path, 0o600)

    # Rebind system outputs
    sys.stdout = SessionOutputWrapper(stdout_path, pretty_path)
    sys.stderr = open(os.devnull, "w")

    # Rebind system input to a non-blocking FIFO wrapper
    sys.stdin = open_stdin_fifo_for_read(stdin_path)

    # --- Verbose Monkey Patching ---
    if verbose and verbose_path:
        v_file = open(verbose_path, "a", encoding="utf-8", buffering=1)
        
        try:
            from openharness.api.client import AnthropicApiClient
            orig_stream_once = AnthropicApiClient._stream_once
            prev_msg_count: list[int] = [0]  # mutable closure counter
            
            async def _patched_stream_once(self_client, request):
                messages = getattr(request, 'messages', [])
                total = len(messages)
                prev = prev_msg_count[0]
                new_msgs = messages[prev:]
                prev_msg_count[0] = total

                v_file.write("\n" + "="*20 + " [LLM API INVOCATION] " + "="*20 + "\n")
                v_file.write(f"Model: {getattr(request, 'model', 'unknown')}  |  ")
                v_file.write(f"Total context: {total} messages  |  ")
                v_file.write(f"New this turn: {len(new_msgs)}\n")

                sys_prompt = getattr(request, 'system_prompt', None)
                if sys_prompt and prev == 0:
                    trunc_sys = sys_prompt[:200] + "... [Truncated]" if len(sys_prompt) > 200 else sys_prompt
                    v_file.write(f"System Prompt: {trunc_sys}\n")

                tools = getattr(request, 'tools', [])
                if tools and prev == 0:
                    v_file.write(f"Tools ({len(tools)} available)\n")

                if new_msgs:
                    v_file.write("\n--- New Messages ---\n")
                    for i, msg in enumerate(new_msgs, prev + 1):
                        role_tag = getattr(msg, 'role', 'UNKNOWN').upper()
                        v_file.write(f"[{i}/{total}] {role_tag}:\n")
                        if hasattr(msg, 'to_api_param'):
                            content = msg.to_api_param().get('content', '')
                        else:
                            content = getattr(msg, 'content', '')
                        if isinstance(content, str):
                            v_file.write(f"{content}\n")
                        else:
                            v_file.write(json.dumps(content, ensure_ascii=False, indent=2) + "\n")
                        v_file.write("\n")

                v_file.write("="*64 + "\n")
                v_file.flush()
                
                async for event in orig_stream_once(self_client, request):
                    yield event

            AnthropicApiClient._stream_once = _patched_stream_once  # type: ignore
        except ImportError:
            v_file.write("Failed to inject verbose API interceptor.\n")
    # -------------------------------

    state = {"id": session_id, "pid": os.getpid(), "status": "running"}
    (d / "state.json").write_text(json.dumps(state, indent=2))


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start_debug_session(session_id: str, verbose: bool = False) -> None:
    d = get_session_dir(session_id).resolve()
    state_file = d / "state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            if state.get("status") == "running" and _pid_alive(state.get("pid", 0)):
                print(f"Session '{session_id}' is already running (PID {state['pid']})")
                return
        except Exception:
            pass

    cmd = [
        sys.executable,
        "-m",
        "openharness",
        "--backend-only",
        "--agent-session",
        session_id,
    ]
    if verbose:
        cmd.append("--agent-verbose")
        
    p = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    print(f"Started agent debug session: {session_id} (PID {p.pid})")
    print(f"Files written to: {d.relative_to(Path.cwd()) if d.is_relative_to(Path.cwd()) else d}")
    time.sleep(1)


def stop_debug_session(session_id: str) -> None:
    d = get_session_dir(session_id).resolve()
    state_file = d / "state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            pid = state.get("pid")
            if pid and _pid_alive(pid):
                os.kill(pid, signal.SIGTERM)
                print(f"Stopped session '{session_id}' (PID {pid})")
            else:
                print(f"Session '{session_id}' is not running.")
        except Exception as e:
            print(f"Could not read state: {e}")

        # Mark as closed
        try:
            state = json.loads(state_file.read_text())
            state["status"] = "closed"
            state_file.write_text(json.dumps(state, indent=2))
        except Exception:
            pass
    else:
        print(f"Session '{session_id}' not found.")


def send_debug_message(session_id: str, message: str) -> None:
    """Send a message to an agent session and tail the streaming output synchronously."""
    d = get_session_dir(session_id).resolve()
    state_file = d / "state.json"
    
    if not state_file.exists():
        print(f"Error: Session '{session_id}' does not exist. Run 'oh agent-debug start {session_id}' first")
        return

    # Check if `message` is raw JSON or plain user input (auto-wraps plain text / slash commands)
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        payload = {"type": "submit_line", "line": message}

    out_file = d / "output"
    if not out_file.exists():
        out_file.touch()

    start_size = out_file.stat().st_size

    # Push to FIFO
    try:
        with open(d / "input", "w", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
            f.flush()
    except OSError as e:
        print(f"Error writing to session '{session_id}': {e}. Is it running?")
        return

    # Synchronous stream collector
    TERMINAL_EVENTS = {"line_complete", "error", "shutdown"}
    with open(out_file, "r", encoding="utf-8") as f:
        f.seek(start_size)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.02)
                continue

            line = line.strip()
            if not line:
                continue

            # Standard protocol stream
            if line.startswith("OHJSON:"):
                # Always echo to terminal
                print(line)
                json_str = line[len("OHJSON:"):]
                try:
                    obj = json.loads(json_str)
                    if obj.get("type") in TERMINAL_EVENTS:
                        break
                except Exception:
                    pass
            else:
                # Raw stdout fallback (e.g uncaught exceptions in backend console)
                print(line)
