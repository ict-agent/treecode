# Gather Handshake Runbook

This runbook records the end-to-end steps for reproducing the recursive
`gather_handshake` workflow in the shared TUI/backend session.

## 1. Install the runtime gather spec

The runtime does **not** read `docs/examples/gather_handshake.md` directly.
`/gather` loads project-local specs from `.openharness/gather/`.

Copy the example spec into the runtime location:

```bash
mkdir -p .openharness/gather
cp docs/examples/gather_handshake.md .openharness/gather/gather_handshake.md
```

If you tune values such as `timeout_seconds`, edit:

```text
.openharness/gather/gather_handshake.md
```

## 2. Start the shared session

Run OpenHarness in the shared TUI/backend mode:

```bash
uv run oh --open-web-console
```

The same workflow can be driven from the TUI or the shared web console.

## 3. Initialize the topology

Use the sequential replay command to create the demo topology:

```text
/execute docs/examples/gather_handshake_bootstrap.txt
```

That script creates:

```text
main
├── A
│   ├── A1
│   └── A2
│       ├── A21
│       ├── A22
│       └── A23
├── B
└── C
```

## 4. Run the contextual gather

Trigger the topology-style handshake gather from the root:

```text
/gather --spec gather_handshake main@default "collect handshake"
```

You can also target a subtree, for example:

```text
/gather --spec gather_handshake A@default "collect handshake"
```

## 5. Expected output

Successful output should include:

- `gather_id`
- `session_id`
- `loaded_spec`
- `timeout_seconds`
- a topology-like text summary
- a JSON payload with `self_result`, `summary_text`, `children`, and `errors`

Typical successful root output looks like:

```text
main@default (root/orchestrator)
├── A-20@default (node A) ── subtree: 6 agents total
│   ├── A1-12@default (leaf worker) [ready]
│   └── A2-10@default (sub-agent)
│       ├── A21-8@default (leaf worker) [ready]
│       ├── A22-6@default (leaf worker) [ready]
│       └── A23-6@default (leaf worker) [ready]
├── B-17@default (leaf node) [ready]
└── C-11@default (leaf node) [ready]
```

## 6. Raw logs and debugging

Global append-only swarm event log:

```text
/home/zhangshuoming/.openharness/data/swarm/events.jsonl
```

Per-agent task logs:

```text
/home/zhangshuoming/.openharness/data/tasks/
```

When debugging:

1. Use the `gather_id` printed by `/gather` to isolate the correct run.
2. Check `loaded_spec` to confirm which gather spec was actually used.
3. Inspect task logs for the relevant agent ids if one subtree times out.

## 7. Current example assumptions

- `gather_handshake` is a contextual, bottom-up LLM workflow.
- Each node processes gather in its own session context.
- Structured tree transport remains deterministic through swarm events.
- The user-facing output is a topology-like summary generated from the root result.
