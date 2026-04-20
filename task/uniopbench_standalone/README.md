# Standalone UniOpBench TreeCode Runner

`run_treecode.py` is intentionally separate from the TreeCode agent framework. It prepares UniOpBench workdirs, invokes `treecode -p` non-interactively, then runs an evaluation epilogue that writes logs and summaries beside each generated kernel.

## Basic Flow

1. Point the script at an existing UniOpBench checkout.
2. Select one or more operators.
3. The script copies each operator into `runs/uniopbench-treecode/<run-id>/operators/<operator>/`.
4. The script writes a platform-specific `TASK.md` and `TREECODE_PROMPT.md`.
5. The script invokes TreeCode in that operator workdir.
6. The script runs:
   - `python test.py --compile-only`
   - `python test.py --no-perf`
   - `python test.py`
   - `python test.py --variants yaml --no-perf`, when supported
7. Full TreeCode stdout, debug trace, evaluation logs, and summaries remain in the workdir.

## Example

```bash
uv run python task/uniopbench_standalone/run_treecode.py \
  --benchmark-root /path/to/UniOpBench \
  --operators activation/relu \
  --model glm-5.1-fp8 \
  --api-format openai \
  --base-url http://localhost:8000/v1 \
  --api-key EMPTY \
  --run-id relu_smoke
```

Use environment/config instead of CLI model flags when preferred. The script does not read model/provider/base URL/API key from UniOpBench yaml files.

```bash
export TREECODE_MODEL=glm-5.1-fp8
export TREECODE_API_FORMAT=openai
export TREECODE_BASE_URL=http://localhost:8000/v1
export OPENAI_API_KEY=EMPTY

uv run python task/uniopbench_standalone/run_treecode.py \
  --benchmark-root /path/to/UniOpBench \
  --operators activation/relu
```

## Hygon K100

```bash
uv run python task/uniopbench_standalone/run_treecode.py \
  --benchmark-root /path/to/UniOpBench \
  --platform hygon-k100 \
  --cuda-arch gfx928 \
  --operators activation/relu
```

## Dry Run

```bash
uv run python task/uniopbench_standalone/run_treecode.py \
  --benchmark-root /path/to/UniOpBench \
  --operators activation/relu \
  --dry-run
```
