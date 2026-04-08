# swarm

Delegate work to subagents and read swarm position without searching the codebase.

## When to use

- User asks how to spawn a teammate, subagent, or parallel worker.
- You need **your own identity** (agent id, parent, root, lineage) → call `swarm_context`.
- You need the **current live tree for this session** → use `swarm_topology(scope="current_session", view="live")` (or the shared web console snapshot).
- You need **global historical topology** → use `swarm_topology(scope="global", view="raw_events")`.
- You need to **greet/check the current live direct children deterministically** → use `swarm_handshake` instead of inventing sender text and combining `send_message` with `task_list`.
- Do **not** rebuild the current tree by scanning `~/.openharness/data/swarm/contexts/`; that directory is historical cache and may include stale, finished, or unrelated agents.

## Create a subagent (primary tool)

Use the **`agent`** tool (not bash):

| Input | Meaning |
|-------|---------|
| `description` | Short label for logs/UI |
| `prompt` | Full task for the subagent |
| `subagent_type` | Logical name, e.g. `reviewer`, `worker-b`, `Explore` (maps to definitions when configured) |
| `agent_name` | Optional explicit runtime identity, e.g. `A`, `A1`, `translator`. Use this when the user asks for a specific child name. |
| `team` | Optional; defaults to `default`. Final id is `name@team` |
| `spawn_mode` | **`oneshot`** (default): runs once and exits — use for almost everything. It will disappear from the live web tree after finishing. **`persistent`**: stays alive for follow-ups via `send_message` and remains available to revisit in the web tree |
| `mode` | Usually leave default; `in_process_teammate` for in-process swarm |

**Naming:** Use `subagent_type` for the capability profile and `agent_name` for the visible runtime identity. If the user explicitly says “create A / A1 / A2”, set `agent_name` to that exact requested name. If the id `name@team` is already taken, OpenHarness auto-renames to `name-1@team`, `name-2@team`, etc.

## Your identity in the interactive REPL

The main session is **`main@default`** in the swarm debugger. Tool metadata sets this so `swarm_context` matches the web tree.

## Slash / TUI

- `/agent-defs` — list/show/init reusable agent profiles from:
  - project-local `.openharness/agents/`
  - global `~/.openharness/agents/`
  - built-in definitions
- `/spawn <profile> <name> <description> [under <agent_id>]` — create a **persistent** child from a reusable profile.
- `/topology` — compact counts for the current shared-session tree.
- `/agents` — current swarm tree (shared session) or **running** tasks in **this repo cwd** only.
- `/agents all` — same, plus non-running tasks for this cwd (capped).
- `/agents select <id>` — focus an agent for inspection (shared session).
- `/tasks clear here` — delete **finished** background task records for this cwd; `/tasks clear all` clears the global task store (completed/failed/killed only).

## Avoid

- Spawning unnamed “agent” over and over (collides with `agent@default`).
- Using `subagent_type` alone when the user asked for a specific child name. Prefer `agent_name="A1"` with an appropriate `subagent_type`.
- Using `/agent-defs` to spawn directly. `/agent-defs` is for discovery and authoring; `/spawn` is the explicit persistent-child command surface.
- `persistent` unless the user needs multi-turn follow-up in that subprocess, wants to switch back to that agent later in the web tree, or wants the agent to remain available for follow-up messages.
