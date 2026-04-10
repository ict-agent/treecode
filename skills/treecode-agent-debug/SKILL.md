---
name: treecode-agent-debug
description: How to use the TreeCode `agent-debug` CLI to programmatically test, trace, and debug TreeCode agent sessions from an external LLM or automated script. Covers session lifecycle, all output file formats, and common usage patterns.
---

# TreeCode Agent Debug Skill

Use `treecode agent-debug` when you need to:
- Write automated E2E tests against TreeCode
- Trace what TreeCode's agent actually does in response to a prompt
- Inspect the raw LLM context (system prompt, tools, history) sent to the model
- Debug unexpected agent behavior without launching the full TUI

---

## Session Lifecycle

Each debug session is identified by a short alphanumeric ID (e.g. `my-test`).

### 1. Start a session

```bash
# Standard session
uv run treecode agent-debug start my-test

# Verbose session (records exact LLM API payloads)
uv run treecode agent-debug start my-test --verbose
```

Files are created under `.treecode/sessions/my-test/`.

### 2. Send messages

```bash
# Plain text prompt (auto-wrapped into the submit_line protocol)
uv run treecode agent-debug send my-test "list the files in the current directory"

# Slash command (sent as-is to the command handler)
uv run treecode agent-debug send my-test "/permissions set full_auto"

# Raw JSON (passed through natively for protocol-level testing)
uv run treecode agent-debug send my-test '{"type": "submit_line", "line": "hello"}'
```

`send` is **synchronous** — it blocks until the agent emits `line_complete`, then prints all `TCJSON:` events and exits. This makes it trivially script-able.

### 3. Stop a session

```bash
uv run treecode agent-debug stop my-test
```

### 4. Clean all sessions

```bash
./scripts/clean_sessions.sh
```

---

## Output Files

All files live in `.treecode/sessions/<ID>/`.

### `output`
Raw NDJSON stream from the backend. Every line is prefixed `TCJSON:` and contains one event object. Useful for machine parsing and assertions.

**Event types emitted:**
| Event | When |
|---|---|
| `transcript_item` | User input or system message recorded |
| `tool_started` | Agent began executing a tool |
| `tool_completed` | Tool returned a result |
| `assistant_complete` | Agent finished responding (includes full message text) |
| `state_snapshot` | Current session state (model, permission mode, etc.) |
| `tasks_snapshot` | Task list status update |
| `line_complete` | Terminal barrier — indicates the turn is fully done |
| `error` | Backend error occurred |

**Example entry:**
```json
TCJSON:{"type":"assistant_complete","message":"The file contains...","item":{"role":"assistant","text":"..."}}
```

---

### `pretty_output.txt`
Clean plain-text conversation log. Filters out `state_snapshot`, `tasks_snapshot`, and slash command echoes, keeping only the conversation-relevant events. Good for human review and LLM context injection.

**Format:**
```
[USER]
list the files in the current directory

[TOOL CALL: bash]
{"command": "ls -la"}

[TOOL RESPONSE]
total 64
drwxr-xr-x  10 user user ...

[ASSISTANT]
The current directory contains the following files...
```

---

### `pretty_output_verbose.txt` *(only with `--verbose`)*
Captures the exact payload sent to the LLM API before every HTTP request. Use this to understand what system prompt, tools, and history the model actually sees.

**Format:**
```
==================== [LLM API INVOCATION] ====================
Model: claude-3-5-sonnet
Max Tokens: 16384
System Prompt: You are an AI assistant... [Truncated]
Tools (38 available)

--- History Context ---
[1/3] USER:
[{"type": "text", "text": "list the files..."}]

[2/3] ASSISTANT:
[{"type": "tool_use", "name": "bash", "input": {"command": "ls -la"}}]

[3/3] USER:
[{"type": "tool_result", "content": "total 64..."}]

================================================================
```

---

### `input` (FIFO)
The named pipe that the `send` subcommand writes to. You can write to it directly for advanced use cases:
```bash
echo '{"type":"submit_line","line":"hello"}' > .treecode/sessions/my-test/input
```

### `state.json`
Session metadata: PID, status (`running` / `closed`), session ID.

---

## Scripting Example

```python
import subprocess

def agent_debug_send(session_id: str, message: str) -> str:
    result = subprocess.run(
        ["uv", "run", "treecode", "agent-debug", "send", session_id, message],
        capture_output=True, text=True
    )
    return result.stdout

# Setup
subprocess.run(["uv", "run", "treecode", "agent-debug", "start", "e2e-test"])
agent_debug_send("e2e-test", "/permissions set full_auto")

# Exercise
output = agent_debug_send("e2e-test", "what is 2 + 2?")

# Assert
assert "assistant_complete" in output
assert '"message"' in output

# Teardown
subprocess.run(["uv", "run", "treecode", "agent-debug", "stop", "e2e-test"])
```

---

## Tips

- Always send `/permissions set full_auto` as the first message to avoid the agent blocking on permission prompts.
- The `send` command waits for `line_complete` — if the agent gets stuck, it will hang. Add a timeout wrapper in long test suites.
- Use `pretty_output.txt` for quick human sanity-checks; use `output` for assertions in test code.
- Use `--verbose` only when debugging what the LLM context actually contains — verbose files can grow very large across multi-turn sessions.
- The session is a persistent process — conversation history accumulates across multiple `send` calls, just like a real chat session.

---

## 相关文档

- **[treecode-dev](../treecode-dev/SKILL.md)** — 开发 TreeCode 的总体操作指引（读码路线、验证清单、常见陷阱）
- **[CLAUDE.md](../../CLAUDE.md)** — 项目总导航
- **[docs/13-Agent开发与调试指南.md](../../docs/13-Agent开发与调试指南.md)** — 面向外部 agent 的开发指南
