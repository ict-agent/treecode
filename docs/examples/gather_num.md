---
name: gather_num
description: Perceive live subtree topology and roll up each node's assigned integer per the active reduction rule.
version: 1
allow_none: true
timeout_seconds: 120
ordering: topology
return_mode: tree
---

# Gather Num

Recursive gather spec: **sense who you are and who your live children are**, then **collect each node's bootstrap integer** and **produce one scalar `subtree_value` per node** by applying the **same reduction rule everywhere** (see below). Nothing here forces addition only—that comes from the **gather request** you pass to `/gather` or `swarm_gather`.

## Canonical file vs runtime copy (avoid drift)

| Location | Role |
|----------|------|
| **`docs/examples/gather_num.md`** (this file in the repo) | **Canonical** — version-controlled source; edit here in PRs. |
| **`<project>/.openharness/gather/gather_num.md`** | **Runtime** — `load_gather_spec()` reads only this path under the project config dir; often gitignored. |

After changing the canonical file, deploy to the runtime location so `/gather` sees it:

```bash
mkdir -p .openharness/gather
cp docs/examples/gather_num.md .openharness/gather/gather_num.md
```

Do **not** maintain two diverging copies: treat `docs/examples/` as truth and **re-copy** when you pull or edit. The header comments in `docs/examples/gather_num_bootstrap.txt` repeat the same commands so you do not have to hunt through other docs.

Bootstrap topology and digits:

```text
/execute docs/examples/gather_num_bootstrap.txt
```

## Reduction rule: spec + request, not contradictory

- **This file** fixes: topology awareness, bootstrap integers are stable, JSON shape, and that each node returns **`subtree_value`** (one number summarizing its whole live subtree under the active rule).
- **The quoted request** on `/gather` (and the same text propagated to children) names the **operator** or instructions: e.g. additive rollup, multiply children then combine with self, coordinator-only product of top-level subtrees, etc.
- Together they **define one workflow**: agents must read **both** the request and this spec and stay **internally consistent**. Changing the request changes the math; you are **not** “overriding” a hidden hard-coded sum in the spec—the spec never mandated only sum.

If you omit nuance in the request, a reasonable default is **sum all assigned integers in the subtree** (see “Default additive demo” below).

## After bootstrap: sync spec (if needed) and run `/gather`

1. Ensure `.openharness/gather/gather_num.md` matches **this** canonical file (see commands above).

2. Wait until spawned agents have finished starting (no need to chat with them unless you want to).

3. From **main**’s session, run gather. `--spec` must match the file stem (`gather_num`). The quoted string is the **request** passed down the tree (it carries the reduction semantics):

   ```text
   /gather --spec gather_num main@default "collect assigned numbers; subtree_value = sum of all assigned integers in this subtree (additive default)"
   ```

   To only roll up under **A** (additive default, expected **`subtree_value` at A = 31** for the demo digits):

   ```text
   /gather --spec gather_num A@default "collect assigned numbers; subtree_value = sum of all assigned integers in this subtree (additive default)"
   ```

Optional: `--gather-id my-run-1` to tag this run in `events.jsonl`.

## Assigned numbers do **not** update during gather

- Each agent’s **bootstrap integer (1–8) is fixed** when `/spawn` runs. Gather does **not** change it and agents should **not** re-roll or overwrite it.
- What updates is only the **derived** scalar **`subtree_value`**, computed from those fixed integers and child **`subtree_value`** fields using the **active reduction rule** from the request.

## Topology and bootstrap digits

```text
main -> (A=1, B=2, C=3)
A -> (A1=4, A2=5)
A2 -> (A21=6, A22=7, A23=8)
```

- All eight workers have distinct integers **1–8** (see `gather_num_bootstrap.txt`).

### Default additive demo (explicit in request)

If every node uses **sum of all assigned integers in its live subtree**:

- **Whole tree (main)**: **36** (= 1+…+8).
- **Subtree rooted at A**: **31** (= 1+4+5+6+7+8).
- **At A2** (for checking intermediate): **26** (= 5+6+7+8).

Use a request that states additive sum explicitly (as in the examples above). Other requests yield other **`subtree_value`** totals; verify by hand against that rule, not against 36/31 unless you asked for addition.

## Task for each participating node

1. Use **`swarm_context`** (and child ids from the gather fan-in) so your result reflects **current live topology**, not guesses.
2. Read your **assigned integer** from the initial bootstrap system/instructions (the spawn prompt). Do not invent a new number.
3. **Leaf** (no live children in this session): set **`subtree_value`** to the value your rule assigns for a single node (usually your assigned integer).
4. **Non-leaf**: after children have reported, compute **`subtree_value`** using the **same rule** as in the gather request, from your `assigned_number` and each child’s structured **`subtree_value`** (use structured child payloads from gather, not free-form scraping).

## Recommended local payload

Return JSON shaped like:

```json
{
  "self_result": {
    "agent_id": "A2@default",
    "assigned_number": 5,
    "role": "worker"
  },
  "subtree_value": 26,
  "summary_text": "A2@default n=5; additive rollup -> subtree_value=26 (children 6,7,8)"
}
```

- **`assigned_number`**: this node's integer from bootstrap.
- **`subtree_value`**: one scalar for this node's whole live subtree under the **active** reduction rule (additive example: sum of all assigned numbers in that subtree).
- **`summary_text`**: short human-readable line: topology + how you combined (so readers see which rule you applied).

You may also include a **`reduction_note`** string in `self_result` if the request is long or non-standard, so parents can audit consistency.

If a node truly has no local contribution (rare), it may set `self_result` to `null` per `allow_none`, but it should still compute **`subtree_value`** for its subtree when it has children.

## Intended use

- Exercise **`swarm_gather`** / **`/gather --spec gather_num`** end-to-end on the demo tree.
- For the **additive** request examples above, **main** should report **`subtree_value` 36** and **A** should report **31**. For other requests, compare results to the rule you stated, not necessarily 36.

Adjust `timeout_seconds` in the **canonical** `docs/examples/gather_num.md`, then `cp` to `.openharness/gather/` again if your model is slow.
