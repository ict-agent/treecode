<h1 align="center">TreeCode</h1>

<p align="center"><strong>Tree-based multi-agent coding harness</strong> — one live agent tree, shared web console, tools, skills, memory, and permissions.</p>

<p align="center">
  <code>treecode</code> · <code>python -m treecode</code>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#acknowledgements">Acknowledgements</a> ·
  <a href="#features">Features</a> ·
  <a href="docs/SHOWCASE.md">Showcase</a> ·
  <a href="LICENSE">MIT</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/React+Ink-TUI-61DAFB?logo=react&logoColor=white" alt="React">
</p>

---

## Acknowledgements

TreeCode draws on **[OpenHarness](https://github.com/HKUDS/OpenHarness)** (HKUDS) for core harness ideas; thanks to that project and its contributors. TreeCode focuses on a **tree-first multi-agent** workflow (live topology, shared web console, swarm tooling).

---

## Quick start

**Prerequisites:** Python 3.10+, [uv](https://docs.astral.sh/uv/), an LLM API key. Optional: Node 18+ for the React TUI frontend.

```bash
# install (from your clone)
uv sync --extra dev

# one-shot prompt
ANTHROPIC_API_KEY=your_key uv run treecode -p "Summarize this repository"

# interactive CLI (default: React TUI when frontend is available)
uv run treecode
```

**Config & data** (defaults):

| What | Where |
|------|--------|
| User config | `~/.treecode/` |
| Override config dir | `TREECODE_CONFIG_DIR` |
| Override data dir | `TREECODE_DATA_DIR` |
| Project markers | `<repo>/.treecode/` |

**Module entry:** `python -m treecode` (same as the `treecode` console script from `uv sync`).

---

## Features (high level)

- **Agent loop** — streaming tool use, retries, hooks, auto-compaction.
- **Tree-shaped multi-agent** — persistent and oneshot children, topology APIs, shared web console + WebSocket backend.
- **42 built-in tools** (+ optional MCP adapters) — file/shell/search/web/tasks/swarm helpers.
- **Skills & plugins** — compatible with common `anthropics/skills` and claude-code-style plugins.
- **Permissions & hooks** — modes, path rules, Pre/PostToolUse.
- **JSON-lines REPL protocol** on stdio, prefixed as **`TCJSON:`**.

For architecture detail, see `docs/` (Chinese) and `CLAUDE.md` for contributor navigation.

---

## Provider / API

Supports **Anthropic-compatible** (default) and **OpenAI-compatible** (`--api-format openai`). Model and base URL can be set via CLI, `~/.treecode/settings.json`, or environment variables such as `TREECODE_MODEL`, `TREECODE_BASE_URL`, `TREECODE_API_FORMAT`.

---

## Development

```bash
uv run ruff check src tests scripts
uv run pytest -q
```

Frontend typecheck (when touching `frontend/terminal`):

```bash
cd frontend/terminal && npx tsc --noEmit
```

---

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center"><em>TreeCode — tree-first multi-agent harness for real coding work.</em></p>
