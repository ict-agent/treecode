# Standalone UniOpBench TreeCode Runner

`run_treecode.py` drives UniOpBench with TreeCode in non-interactive mode. It is intentionally kept outside the TreeCode agent framework: it prepares one isolated workdir per UniOpBench operator, invokes `treecode -p` in that workdir, then runs a fixed evaluation epilogue and stores traces beside the generated kernel.

## What It Does

For each selected operator, the runner:

1. Copies `benchmarks/UniOpBench/operators/<operator>/` into `runs/uniopbench-treecode/<run-id>/operators/<operator-key>/`.
2. Removes stale generated artifacts such as `cuda_/kernel.cu`, compiled libraries, and Python caches.
3. Creates `TASK.md` and `TREECODE_PROMPT.md` for the target platform.
4. Invokes TreeCode with `--cwd <operator-workdir>`, `--dangerously-skip-permissions`, `--debug-output`, and `-p`.
5. Runs the evaluation epilogue:
   - `python test.py --compile-only`
   - `python test.py --no-perf`
   - `python test.py`
   - `python test.py --variants yaml --no-perf`, when the operator supports variants
6. Writes per-operator summaries and a top-level `run_summary.json`.

The generated prompt uses TreeCode tool names explicitly: `read_file`, `write_file`, `edit_file`, and `bash`.

## Requirements

- Run commands from the TreeCode repository root.
- Have a UniOpBench checkout available. By default the script looks for `benchmarks/UniOpBench`; override it with `--benchmark-root` or `UNIOPBENCH_ROOT`.
- Have the target platform environment ready for UniOpBench evaluation, for example CUDA, PyTorch, compiler toolchain, and any UniOpBench Python dependencies.
- Configure TreeCode model access through CLI flags, environment variables, or TreeCode settings.

This runner does not read model/provider/base URL/API key from UniOpBench YAML files.

## Configure vLLM / OpenAI-Compatible Endpoint

Use TreeCode's OpenAI-compatible configuration:

```bash
export TREECODE_MODEL=glm-5.1-fp8
export TREECODE_API_FORMAT=openai
export TREECODE_BASE_URL=http://HOST:PORT/v1
export OPENAI_API_KEY=YOUR_API_KEY
export TREECODE_MAX_TOKENS=128000
```

If you previously used Claude Code environment variables, clear them before running TreeCode. `ANTHROPIC_BASE_URL` can override the intended TreeCode base URL and lead to confusing 404s.

```bash
unset ANTHROPIC_BASE_URL
unset ANTHROPIC_AUTH_TOKEN
unset ANTHROPIC_API_KEY
unset ANTHROPIC_DEFAULT_HAIKU_MODEL
unset ANTHROPIC_DEFAULT_SONNET_MODEL
unset ANTHROPIC_DEFAULT_OPUS_MODEL
```

You can also pass model settings directly to the runner:

```bash
uv run python task/uniopbench/run_treecode.py \
  --benchmark-root benchmarks/UniOpBench \
  --operators activation/relu \
  --model glm-5.1-fp8 \
  --api-format openai \
  --base-url http://HOST:PORT/v1 \
  --api-key YOUR_API_KEY \
  --max-tokens 128000 \
  --run-id relu_smoke
```

`--api-key` is redacted from runner command metadata, but it may still be visible in shell history. Prefer environment variables for shared machines.

## Run Operators

Run one operator:

```bash
uv run python task/uniopbench/run_treecode.py \
  --benchmark-root benchmarks/UniOpBench \
  --operators activation/relu \
  --run-id relu_smoke
```

Run multiple operators:

```bash
uv run python task/uniopbench/run_treecode.py \
  --benchmark-root benchmarks/UniOpBench \
  --operators activation/relu,norm/rmsnorm \
  --run-id two_ops \
  --keep-going
```

If `--operators` is omitted, the runner expands to all operators under `operators/**/test.py`.

If you reuse an existing `--run-id`, add `--overwrite` to rebuild the operator workdirs:

```bash
uv run python task/uniopbench/run_treecode.py \
  --benchmark-root benchmarks/UniOpBench \
  --operators activation/relu,norm/rmsnorm \
  --run-id two_ops \
  --overwrite \
  --keep-going
```

Without `--overwrite`, the runner stops when an operator workdir already exists. This prevents accidentally deleting a generated kernel and its trace.

## Hygon K100

```bash
uv run python task/uniopbench/run_treecode.py \
  --benchmark-root benchmarks/UniOpBench \
  --platform hygon-k100 \
  --cuda-arch gfx928 \
  --operators activation/relu \
  --run-id relu_hygon
```

For CUDA, the default arch is `sm_80`. Override it with `--cuda-arch` when needed.

## Dry Run

Dry run prepares workdirs, `TASK.md`, and `TREECODE_PROMPT.md` without invoking TreeCode or evaluation:

```bash
uv run python task/uniopbench/run_treecode.py \
  --benchmark-root benchmarks/UniOpBench \
  --operators activation/relu \
  --run-id inspect_prompt \
  --dry-run \
  --overwrite
```

This is useful for inspecting the exact prompt before spending model or GPU time.

## Extra TreeCode Arguments

Forward raw TreeCode CLI arguments with `--treecode-arg`. Repeat the flag when passing multiple groups:

```bash
uv run python task/uniopbench/run_treecode.py \
  --benchmark-root benchmarks/UniOpBench \
  --operators activation/relu \
  --treecode-arg "--max-turns 40" \
  --treecode-arg "--output-format text"
```

Use `--treecode-cmd` if `treecode` is not on `PATH` or you need a wrapper command:

```bash
uv run python task/uniopbench/run_treecode.py \
  --treecode-cmd "uv run treecode" \
  --benchmark-root benchmarks/UniOpBench \
  --operators activation/relu
```

## Artifacts

For `--run-id two_ops` and operator `activation/relu`, the workdir is:

```text
runs/uniopbench-treecode/two_ops/operators/activation__relu/
```

Important files:

- `TASK.md`: platform-specific task contract given to the model.
- `TREECODE_PROMPT.md`: exact non-interactive prompt passed with `-p`.
- `run_metadata.json`: benchmark root, operator, platform, and arch metadata.
- `cuda_/kernel.cu`: generated kernel.
- `GENERATION_NOTES.md`: model-written summary, when produced.
- `trace/treecode_stdout.log`: raw TreeCode stdout. Console output skips blank lines, but this log keeps the raw stream.
- `trace/treecode_debug.log`: TreeCode debug trace.
- `evaluation/compile_only.log`: compile-only evaluation log.
- `evaluation/verify.log`: correctness log without perf.
- `evaluation/perf.log`: full evaluation log.
- `evaluation/variants.log`: variant correctness log, when supported.
- `evaluation/final_kernel.cu`: copy of the final generated kernel, when present.
- `summary.json` and `summary.md`: per-operator result.

The run-level summary is:

```text
runs/uniopbench-treecode/<run-id>/run_summary.json
```

## Exit Status

- `0`: all selected operators reached `passed`, `generated`, or `dry_run`.
- `1`: TreeCode failed, required evaluation failed, or an exception occurred.

With `--keep-going`, later operators still run after a failure, but the final exit status remains non-zero if any operator fails.

## Troubleshooting

`unknown tool: read`

The generated prompt now names only TreeCode's real tools. If this still appears, you are likely reusing an old workdir with an old `TREECODE_PROMPT.md`. Re-run with `--overwrite` or use a new `--run-id`.

The entry prompt is self-contained and no longer asks the model to inspect `TASK.md` first. `TASK.md` is still written for traceability, but removing that first-read step avoids some OpenAI-compatible models mapping the action to a non-existent `read` tool.

`invalid input for bash: command Field required`

The model emitted a `bash` tool call without the required `command` argument. Fresh prompts include the exact TreeCode tool argument shapes, including `bash` as `{"command": "..."}`. If this still appears, first rerun with `--overwrite` or a new `--run-id` so the generated `TASK.md` and `TREECODE_PROMPT.md` are refreshed.

404 from the model endpoint

Check the exact endpoint TreeCode is using. For OpenAI-compatible vLLM, the base URL should normally end in `/v1`, for example `http://HOST:PORT/v1`. Also clear stale `ANTHROPIC_*` variables if they were set for Claude Code.

```bash
curl -sS "$TREECODE_BASE_URL/models" \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

Evaluation fails but TreeCode generated `cuda_/kernel.cu`

Inspect `evaluation/verify.log` first, then `trace/treecode_stdout.log`. The runner keeps the generated workdir intact unless you rerun with `--overwrite`.

Need only prompt generation

Use `--dry-run`. There is no eval-only resume mode; the runner prepares a fresh operator workdir at the start of each operator run.
