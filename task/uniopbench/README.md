# UniOpBench Task

This directory contains the repository-owned orchestration layer for running LLM kernel-generation experiments against the external [UniOpBench](../../benchmarks/UniOpBench) benchmark.

It does not modify the upstream UniOpBench source tree. Instead, it:
- reads an experiment config from `task.yaml`
- copies each selected operator into an isolated run workspace
- invokes the full TreeCode non-interactive runtime inside that workspace
- lets the agent edit only `cuda_/kernel.cu`
- runs the copied operator's native `python test.py ...` commands
- stores prompts, agent traces, generated artifacts, and test logs under `task/task_results/uniopbench/<experiment.name>/runs/`

## Files

- [task.yaml](task.yaml): experiment config
- [TASK.md](TASK.md): task prompt injected into the TreeCode runtime
- [OPTIMIZE_TASK.md](OPTIMIZE_TASK.md): task prompt for optimization rounds (perf-focused)
- [orchestrator.py](orchestrator.py): benchmark runner implementation
- [cli.py](cli.py): CLI argument parsing and entrypoint (invoked via `treecode --task uniopbench`)
- [task_vllm_example.yaml](task_vllm_example.yaml): vLLM config template

## Quick Run

From the repository root, initialize the benchmark submodule once:

```bash
git submodule update --init --recursive benchmarks/UniOpBench
```

Use a dry run to confirm the config, operator selection, and prompt generation without calling a model:

```bash
uv run --extra dev treecode --task uniopbench --operators activation/relu --run-id relu_smoke --dry-run
```

UniOpBench inherits model access from the normal TreeCode launch path. Use the same flags or settings you would use for an ordinary TreeCode session:

```bash
uv run --extra dev treecode --model claude-sonnet-4-20250514 \
  --task uniopbench --operators activation/relu --run-id relu_smoke
```

To run through a vLLM OpenAI-compatible endpoint, start vLLM first and pass the endpoint through TreeCode launch settings. The checked-in yaml intentionally does not contain public or private endpoint URLs, API keys, providers, or model names.

```bash
uv run --extra dev treecode \
  --model glm-5.1-fp8 \
  --api-format openai \
  --base-url http://localhost:8000/v1 \
  --api-key EMPTY \
  --task uniopbench \
  --config task/uniopbench/task_vllm_example.yaml \
  --operators activation/relu \
  --run-id vllm_relu_smoke
```

If you split the command across lines, the backslash must be the final character on each continued line:

```bash
uv run --extra dev treecode --task uniopbench \
  --config task/uniopbench/task_vllm_example.yaml \
  --operators activation/relu \
  --run-id vllm_relu_smoke
```

The run output is written under `task/task_results/uniopbench/<experiment.name>/runs/<run_id>/`.

## Config

`task.yaml` defines:
- `experiment`: run name, repair budget, target CUDA arch, optional `max_agent_steps` (0 = unlimited)
- `operators`: explicit operator list, or `all`
- `prompt`: optional extra prompt fragments
- `runtime`: run-level behavior such as fail-fast and temp-build cleanup

### Model Configuration

UniOpBench does not read provider, base URL, API key, API format, model, or max-token settings from its yaml files. Those settings come from the top-level TreeCode launch exactly as they do for a normal TreeCode session:

- CLI flags: `--model`, `--api-format`, `--base-url`, `--api-key`
- Environment variables: `TREECODE_MODEL`, `TREECODE_API_FORMAT`, `TREECODE_BASE_URL`, `TREECODE_MAX_TOKENS`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- TreeCode settings: `~/.treecode/settings.json`

Task-specific settings such as operator selection, CUDA architecture, repair rounds, and output layout stay in `task/uniopbench/*.yaml`.

### Using a local vllm serve model

To use a model served locally via `vllm serve` (e.g. GLM-5, Qwen, etc.):

1. Start vllm:
   ```bash
   python -m vllm.entrypoints.openai.api_server \
       --model THUDM/glm-4-9b-chat --port 8000
   ```

2. Launch TreeCode with OpenAI-compatible settings:
   ```bash
   treecode \
     --model glm5 \
     --api-format openai \
     --base-url http://localhost:8000/v1 \
     --api-key EMPTY \
     --task uniopbench \
     --config task/uniopbench/task_vllm_example.yaml \
     --operators activation/relu
   ```

   Environment-variable form:
   ```bash
   export TREECODE_MODEL="glm5"
   export TREECODE_API_FORMAT="openai"
   export TREECODE_BASE_URL="http://localhost:8000/v1"
   export OPENAI_API_KEY="EMPTY"

   treecode --task uniopbench --config task/uniopbench/task_vllm_example.yaml --operators activation/relu
   ```

See [task_vllm_example.yaml](task_vllm_example.yaml) for a complete example config.

### Standard example

Example:

```yaml
experiment:
  name: a100_uniopbench_v1
  max_repair_rounds: 3
  # max_agent_steps: 0   # optional; mapped to a high TreeCode turn cap
  cuda_arch: sm_80

operators:
  - activation/relu
  - conv/depthwiseconv
```

To run every operator:

```yaml
operators:
  - all
```

## Run

From the repository root:

```bash
treecode --task uniopbench
```

Useful variants:

```bash
treecode --task uniopbench --operators all --dry-run
treecode --task uniopbench --operators norm/rmsnorm
treecode --task uniopbench --run-id my_run
treecode --task uniopbench --resume --run-id my_run
```

## Optimize

The `optimize` subcommand is a self-contained workflow for iterative kernel performance improvement. It does **not** require a prior `run` — it can generate a kernel from scratch or start from a reference implementation.

```bash
# From scratch: first round generates the kernel, subsequent rounds optimize
treecode --task uniopbench --operators norm/rmsnorm optimize --rounds 3 --target-speedup 1.5

# With a reference kernel (copied as v0 baseline, not counted as a round)
treecode --task uniopbench --operators norm/rmsnorm optimize \
  --rounds 3 --target-speedup 1.5 \
  --ref-impl path/to/kernel.cu

# Give up after 2 versioning rounds if target not met (separate from --rounds)
treecode --task uniopbench --operators norm/rmsnorm optimize --rounds 5 --max-version 2 --target-speedup 1.5

# Dry run to inspect prompts without calling the LLM
treecode --task uniopbench --operators norm/rmsnorm optimize --rounds 2 --dry-run

# Resume a prior optimize run id and skip operators already recorded in run_summary.json
treecode --task uniopbench --operators norm/rmsnorm optimize --resume --run-id my_opt_run
```

### Optimize flow

For each operator:
1. Copies operator scaffold into a fresh `artifact/` directory
2. If `--ref-impl` is given, copies it as `v0_baseline.cu` (not counted as a round)
3. Runs up to `--rounds` agent sessions (pass@k context restarts):
   - Round 1 without ref-impl: uses the generation prompt (`TASK.md`) to create the kernel from scratch
   - Subsequent rounds: uses the optimization prompt (`OPTIMIZE_TASK.md`)
4. **Two-layer limits**: `--rounds` = max context restarts (pass@k); `--max-version` = max number of versions before give-up when target not met (default: same as `--rounds`). Optimization stops as soon as the manifest has `max_version` versions (including intermediate attempts).
5. Each round's kernel is saved as a versioned snapshot in `versions/`
6. **Intermediate versions**: The agent is instructed to save each passing kernel (correctness + perf) to `versions/round_N_attempt_M.cu` before making further edits. All such versions are collected and added to the manifest.
7. If correctness breaks, the kernel is reverted to the last good version
8. Early-stops when `--target-speedup` is met
9. **Give-up**: When the manifest reaches `--max-version` versions without meeting target, optimization stops and `optimization_summary.md` is written with version history and performance comparison.
10. Selects the best-performing version and copies it back to `artifact/cuda_/kernel.cu`

### Kernel versioning

Each operator tracks versions in `versions/manifest.json`. All versions that pass correctness and can run perf (even if below target) are saved:

```json
{
  "versions": [
    {"version": "v0_baseline", "file": "v0_baseline.cu", "speedup": null, "source": "ref_impl"},
    {"version": "v1_opt", "file": "v1_opt.cu", "speedup": 0.19, "source": "round_1", "correctness": true},
    {"version": "v2_attempt_1", "file": "v2_attempt_1.cu", "speedup": 0.42, "source": "round_2", "correctness": true},
    {"version": "v2_attempt_2", "file": "v2_attempt_2.cu", "speedup": 0.66, "source": "round_2", "correctness": true},
    {"version": "v2_opt", "file": "v2_opt.cu", "speedup": 0.66, "source": "round_2", "correctness": true}
  ],
  "best": "v2_attempt_2",
  "best_speedup": 0.66,
  "target_speedup": 0.8
}
```

When target is not met and the manifest reaches `--max-version` versions, `optimization_summary.md` is written with a give-up report (version history table and best version).

## Execution Model

Each operator runs in an **isolated live agent workflow**:
- **Workspace**: Each operator gets its own workspace (`artifact/` directory); no shared workspace across operators.
- **Context**: Each repair round starts a fresh TreeCode non-interactive session. No conversation history is carried across rounds; only the regenerated prompt carries prior kernel/log context forward.

For each operator, the orchestrator:
1. copies the upstream operator into a run-local `artifact/` directory
2. builds a round system prompt from `TASK.md` plus the operator scaffold
3. writes each round's detailed prompt and request metadata into the run directory
4. launches the TreeCode runtime for that round with the operator's artifact as the workspace root
5. submits one autonomous user turn per repair round
6. lets the agent inspect files, edit `cuda_/kernel.cu`, and run the operator's native test commands
7. if compile or correctness fails, writes a new repair request file with the prior kernel and logs, then starts a new live session for the next round

Success is currently defined as:
- `python test.py --compile-only` passes
- `python test.py --no-perf` passes
- if variants are supported, `python test.py --variants yaml --no-perf` passes

Performance is recorded, but it is not currently used as the pass/fail gate.

## Output Layout

Runs are written to:

- `task/task_results/uniopbench/<experiment.name>/runs/`

The `experiment.name` comes from `task.yaml` (e.g. `a100_uniopbench_v1`). Each run looks like:

```text
<experiment.name>/runs/<run_id>/
  run_summary.json
  console.log
  operators/
    activation__relu/
      prompt/
        system.txt
        user.txt
      rounds/
        round_0/              # run subcommand: round_0, round_1, ...
          agent.log           # optimize subcommand: round_1, round_2, ...
          trajectory.log
          request.json
          response.json
          extracted_kernel.cu
          verify.log
          perf.log
          variants.log
      versions/               # optimize only
        manifest.json
        v0_baseline.cu
        v1_initial.cu / v1_opt.cu
        v2_attempt_1.cu       # intermediate (when agent saves)
        v2_attempt_2.cu
        v2_opt.cu
        optimization_summary.md  # when target not met
      artifact/
        ...
      result.json
```

## Notes

- This task layer assumes UniOpBench dependencies are already installed in the environment you use to run it.
- The orchestrator uses TreeCode's normal tool-aware runtime, not a direct one-shot LLM call.
- `enable_torch_compile_baseline` is currently recorded in metadata only; it is not injected into the external UniOpBench runner.
