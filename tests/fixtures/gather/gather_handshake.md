---
name: gather_handshake
description: Recursively gather a topology-like handshake tree from the current subtree.
version: 1
allow_none: true
timeout_seconds: 20
ordering: topology
return_mode: tree
---

# Gather Handshake

Use this spec when a node wants to recursively gather a topology-like handshake
report from its live descendants.

## Intent

Each node should treat gather as a real task in its own session context.
Leaf nodes contribute a compact local handshake payload.
Non-leaf nodes recurse first, then synthesize an upward topology-like summary
using both their own context and collected child results.

## Node Rules

- Every node should identify itself with its current `agent_id`.
- A node may report a role label based on its local purpose in the current task.
- A node should report whether it is ready to continue collaborating.
- A node may include a short local status note.
- If child results are already available, a non-leaf node should incorporate them
  into a topology-like upward summary.
- If a node truly has no local contribution for this gather, it may return `null`
  for `self_result` when the caller allows it.

## Output Contract

The recursive gather should preserve a tree-shaped result with:

- `agent_id`
- `status`
- `self_result`
- `children`
- `summary_text`

The preferred synthesis payload for this spec is:

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

Leaf nodes return their local payload directly.
Non-leaf nodes recurse first, then return the same shape with gathered children.
