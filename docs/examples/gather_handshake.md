---
name: gather_handshake
description: Recursively gather a topology-like handshake tree from the current subtree.
version: 1
allow_none: true
timeout_seconds: 120
ordering: topology
return_mode: tree
---

# Gather Handshake

`gather_handshake.md` is the reference example for recursive gather specs.

## Canonical file vs runtime copy

| Location | Role |
|----------|------|
| **`docs/examples/gather_handshake.md`** (this file in the repo) | **Canonical** — edit here in PRs. |
| **`<project>/.openharness/gather/gather_handshake.md`** | **Runtime** — `load_gather_spec()` reads only this path; often gitignored. |

Deploy the canonical file after edits:

```bash
mkdir -p .openharness/gather
cp docs/examples/gather_handshake.md .openharness/gather/gather_handshake.md
```

The same commands appear in the header of `docs/examples/gather_handshake_bootstrap.txt` so you do not need to search other docs.

It demonstrates a simple, efficient pattern:

1. Each node processes gather as a real task in its own session context.
2. Leaf nodes synthesize a topology-like local summary and upward payload.
3. Non-leaf nodes recurse into their live children first.
4. Parents use their own LLM context plus collected child results to synthesize an upward topology-like result.

## Recommended Local Payload

Each node should produce:

```json
{
  "self_result": {
    "agent_id": "A2@default",
    "role": "worker",
    "ready": true,
    "status_note": "idle and waiting"
  },
  "summary_text": "A2@default [branch, ready]\n- A21@default [leaf, ready]\n- A22@default [leaf, ready]"
}
```

The node should write a short topology-like textual summary and also provide the
structured `self_result` it wants to pass upward.

If the current workflow explicitly says that a node has no local contribution, it
may return `null` for `self_result`, but it should still produce a useful
`summary_text` when possible.

## Intended Use

This spec is meant to recreate a topology-like handshake subtree entirely
through recursive gather, without relying on ad-hoc message scraping.

Each participating node should:

1. Use its own current session context to understand who it is.
2. Incorporate any gathered child results that are already available.
3. Produce a topology-like upward summary for its subtree.
4. Return both `self_result` and `summary_text` so the gather protocol can keep
   a structured tree while the initiator sees a readable topology report.

For a tree such as:

```text
main -> (A, B, C)
A -> (A1, A2)
A2 -> (A21, A22, A23)
```

invoking gather from `A` should yield a structured subtree rooted at `A`,
including each descendant's handshake payload and recursive child results.
