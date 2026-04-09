---
name: gather_num
description: Perceive live subtree topology and roll up each node's assigned integer.
version: 1
allow_none: true
timeout_seconds: 120
ordering: topology
return_mode: tree
---

# Gather Num

Recursive gather spec: **sense who you are and who your live children are**, then **collect each node's bootstrap integer** and aggregate upward.

Runtime note: `/gather` and `swarm_gather` load the project-local file  
`.openharness/gather/gather_num.md`. Copy this example there before running:

```bash
mkdir -p .openharness/gather
cp docs/examples/gather_num.md .openharness/gather/gather_num.md
```

Bootstrap the same tree and numbers with:

```text
/execute docs/examples/gather_num_bootstrap.txt
```

## After bootstrap: install spec and run `/gather`

1. Copy this file so the runtime can load it (once per project):

   ```bash
   mkdir -p .openharness/gather
   cp docs/examples/gather_num.md .openharness/gather/gather_num.md
   ```

2. Wait until spawned agents have finished starting (no need to chat with them unless you want to).

3. From **main**’s session, run gather. `--spec` must match the file stem (`gather_num`). The quoted string is the **request** passed down the tree:

   ```text
   /gather --spec gather_num main@default "collect assigned numbers and subtree sums"
   ```

   To only roll up under **A** (expected `subtree_sum` **31** for this demo):

   ```text
   /gather --spec gather_num A@default "collect assigned numbers and subtree sums"
   ```

Optional: `--gather-id my-run-1` to tag this run in `events.jsonl`.

## Assigned numbers do **not** update during gather

- Each agent’s **bootstrap integer (1–8) is fixed** when `/spawn` runs. Gather does **not** change it and agents should **not** re-roll or overwrite it.
- What changes in the pipeline is only the **aggregated** field: each node computes **`subtree_sum`** from its constant `assigned_number` plus children’s reported `subtree_sum` values. That is a **derived** roll-up, not a new random assignment.

## Topology and expected integers

```text
main -> (A=1, B=2, C=3)
A -> (A1=4, A2=5)
A2 -> (A21=6, A22=7, A23=8)
```

- All eight workers have distinct integers **1–8** (see `gather_num_bootstrap.txt`).
- **Whole-tree sum** (all eight nodes): **36**.
- **Subtree at A** (nodes A, A1, A2, A21–A23): **1+4+5+6+7+8 = 31**.

## Task for each participating node

1. Use **`swarm_context`** (and child ids from the gather fan-in) so your result reflects **current live topology**, not guesses.
2. Read your **assigned integer** from the initial bootstrap system/instructions (the spawn prompt). Do not invent a new number.
3. **Leaf** (no live children in this session): return your integer; `subtree_sum` equals that integer.
4. **Non-leaf**: after children have reported, set  
   `subtree_sum = your_integer + sum(each child's subtree_sum)`  
   (use the structured child payloads from gather, not free-form scraping).

## Recommended local payload

Return JSON shaped like:

```json
{
  "self_result": {
    "agent_id": "A2@default",
    "assigned_number": 5,
    "role": "worker"
  },
  "subtree_sum": 26,
  "summary_text": "A2@default n=5; children A21(6), A22(7), A23(8) -> subtree_sum=26"
}
```

- **`assigned_number`**: this node's integer from bootstrap.
- **`subtree_sum`**: this node's integer **plus** all descendants' integers in the live subtree (recursive definition).
- **`summary_text`**: short human-readable line: topology snippet + numbers so the initiator can read a report without only parsing JSON.

If a node truly has no local contribution (rare), it may set `self_result` to `null` per `allow_none`, but it should still pass through child sums when it has children.

## Intended use

- Validate **`swarm_gather`** / **`/gather --spec gather_num`** end-to-end on the demo tree.
- From **main**, the rolled-up total over **A + B + C** subtrees should match **36** (all eight workers). From **A** alone, **`subtree_sum` at A** should be **31**.

Adjust `timeout_seconds` in `.openharness/gather/gather_num.md` if your model is slow.
