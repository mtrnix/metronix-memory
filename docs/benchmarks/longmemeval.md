# LongMemEval-S Benchmark with Metronix

Measure Metronix agent memory on the [LongMemEval-S](https://github.com/xiaowu0162/LongMemEval) benchmark (ICLR 2025). Metronix is the **memory backend only** — answer generation and LLM-judge evaluation use external OpenAI-compatible APIs.

Quick start: [benchmarks/longmemeval/README.md](../../benchmarks/longmemeval/README.md).

## What this measures

LongMemEval evaluates long-term chat-assistant memory across six question types:

- Information extraction
- Multi-session reasoning
- Temporal reasoning
- Knowledge updates
- Abstention
- Preferences

**LongMemEval-S** uses 115k tokens of conversation history per question (~40 sessions). For a fast pipeline check, use the `**oracle`** variant (evidence sessions only).

Official metric: **QA accuracy** via an LLM judge (GPT-4o in the paper). You can use any OpenAI-compatible judge model; scores are only comparable to the paper when using the same models.

Per question:

1. `agent_id = lme-{question_id}` in workspace `MABENCH`
2. Ingest each haystack session via `metronix_memory_store`
3. Retrieve context via `metronix_memory_search`
4. Generate answer with chat LLM → append `{question_id, hypothesis}` to JSONL
5. Evaluate with LLM judge → accuracy overall and by `question_type`

## Prerequisites

- Metronix running: `curl http://localhost:8000/health`
- Docker Compose stack from [install.md](../../install.md)
- Python **3.11+** (benchmark venv, separate from container Python)
- Disk space for datasets (~100 MB for `s` variant)
- LLM API keys (OpenAI-compatible)

After a standard install, only workspace `**MTRNIX`** exists. Benchmark data uses a separate workspace `**MABENCH**` (created automatically by setup/preflight or manually — see below).

## Environment variables {#environment-variables}

### Where to put configuration

The benchmark uses **its own env file**, separate from the repo-root Metronix install config:


| File                                        | Purpose                                                                               |
| ------------------------------------------- | ------------------------------------------------------------------------------------- |
| `**benchmarks/longmemeval/.env.benchmark`** | **Edit this** — chat/judge LLM keys, Metronix MCP URL, workspace, retrieval settings  |
| **Repo-root `.env`**                        | Metronix Docker stack (from `install.sh`). Optional source for `METRONIX_MCP_API_KEY` |


Do **not** put `LME_`* variables in the repo-root `.env`. They are read only from `benchmarks/longmemeval/.env.benchmark`.

Create your benchmark env file:

```bash
cd benchmarks/longmemeval
cp .env.benchmark.example .env.benchmark
# Edit .env.benchmark before the first run
```

On Windows (PowerShell):

```powershell
cd benchmarks\longmemeval
Copy-Item .env.benchmark.example .env.benchmark
# Edit .env.benchmark
```

`bash ./setup.sh` / `setup.ps1` create `.env.benchmark` automatically if it is missing (and migrate legacy `.env` in this folder if present).

### MCP URL (`METRONIX_MCP_URL`)

Default from your machine: `**http://localhost:8000/mcp**`.

This is the `**metronix-full-api**` Docker container (`metronix-core` service in `docker-compose.full.yml`), API port **8000**, path `**/mcp`**.  
`METRONIX_API_URL` is the same host/port **without** `/mcp` (`http://localhost:8000`).

From another container on the same Compose network use `http://metronix-core:8000/mcp` instead of `localhost`. See `[docs/MCP_API.md](../MCP_API.md)`.

### Variable reference


| Variable               | Required | Default                     | Purpose                            | Where to get it                                                              |
| ---------------------- | -------- | --------------------------- | ---------------------------------- | ---------------------------------------------------------------------------- |
| `METRONIX_MCP_API_KEY` | yes      | —                           | Bearer token for `/mcp`            | Copy into `.env.benchmark`, or leave blank and load from repo-root `.env`    |
| `METRONIX_MCP_URL`     | no       | `http://localhost:8000/mcp` | MCP endpoint                       | Default: `**metronix-full-api`** / `metronix-core:8000` + `/mcp` (see above) |
| `METRONIX_API_URL`     | no       | `http://localhost:8000`     | REST API for preflight / workspace | Same container/port as MCP, **without** `/mcp`                               |
| `LME_WORKSPACE_ID`     | no       | `MABENCH`                   | Isolated benchmark workspace       | Leave default; created by setup                                              |
| `LME_CHAT_API_KEY`     | yes*     | —                           | Chat LLM API key                   | Your provider; fallback: `OPENAI_API_KEY`                                    |
| `LME_CHAT_BASE_URL`    | no       | `https://api.openai.com/v1` | Chat endpoint                      | OpenAI, DeepSeek, local vLLM/Ollama, etc.                                    |
| `LME_CHAT_MODEL`       | yes      | `gpt-4o-mini`               | Model for answers                  | Any OpenAI-compatible model name                                             |
| `LME_JUDGE_API_KEY`    | yes**    | —                           | Judge API key                      | Same as chat or separate; fallback chain below                               |
| `LME_JUDGE_BASE_URL`   | no       | `https://api.openai.com/v1` | Judge endpoint                     | Recommend OpenAI for paper-comparable scores                                 |
| `LME_JUDGE_MODEL`      | no       | `gpt-4o`                    | Judge model                        | Recommend `gpt-4o` for paper protocol                                        |
| `LME_RETRIEVE_TOP_K`   | no       | `10`                        | Memory hits in answer prompt       | Tune as needed                                                               |
| `OPENAI_API_KEY`       | fallback | —                           | Legacy alias                       | Used if `LME_`* keys are empty                                               |


 * Required; falls back to `OPENAI_API_KEY` if empty.  
 ** Required for evaluation; falls back to `LME_CHAT_API_KEY` → `OPENAI_API_KEY`.

**Minimum for smoke:**

1. `METRONIX_MCP_API_KEY` — in `.env.benchmark` or repo-root `.env`
2. `LME_CHAT_API_KEY` — from your LLM provider
3. `LME_JUDGE_API_KEY` — same or separate key

**Example (OpenAI):**

```bash
METRONIX_MCP_API_KEY=fa76dc4d...
METRONIX_MCP_URL=http://localhost:8000/mcp
METRONIX_API_URL=http://localhost:8000
LME_WORKSPACE_ID=MABENCH

LME_CHAT_API_KEY=sk-proj-...
LME_CHAT_BASE_URL=https://api.openai.com/v1
LME_CHAT_MODEL=gpt-4o-mini

LME_JUDGE_API_KEY=sk-proj-...
LME_JUDGE_BASE_URL=https://api.openai.com/v1
LME_JUDGE_MODEL=gpt-4o
```

**Example (DeepSeek chat + OpenAI judge):**

```bash
LME_CHAT_BASE_URL=https://api.deepseek.com/v1
LME_CHAT_MODEL=deepseek-chat
LME_CHAT_API_KEY=sk-...

LME_JUDGE_BASE_URL=https://api.openai.com/v1
LME_JUDGE_MODEL=gpt-4o
LME_JUDGE_API_KEY=sk-...
```

> Scores with non-paper models (DeepSeek, local Ollama, etc.) are valid for **self-hosted regression** but should **not** be compared directly to ICLR paper numbers. Always report `LME_CHAT_MODEL` and `LME_JUDGE_MODEL` in results.

Verify env without printing secrets:

```bash
python scripts/preflight.py --check-env-only
```

CLI overrides (Path B): `run_benchmark.py run --chat-model ... --chat-base-url ... --chat-api-key ...`

## Recommended models


| Role  | Recommendation | Notes                                                |
| ----- | -------------- | ---------------------------------------------------- |
| Chat  | `gpt-4o-mini`  | Cheaper for full runs; use `gpt-4o` for max accuracy |
| Judge | `gpt-4o`       | Official LongMemEval eval protocol                   |


## Workspace `MABENCH`

Benchmark memory is isolated from daily use in `MTRNIX`. `**MABENCH**` is not created by `install.sh`.

### Automatic (Path A / preflight)

`bash ./setup.sh` / `setup.ps1` and `preflight.py --ensure-workspace` idempotently create `MABENCH`:

- `GET /api/v1/workspaces/` — check existence
- `POST /api/v1/workspaces/` with `workspace_id: "MABENCH"`

### Manual (Path B)

```bash
curl -s http://localhost:8000/api/v1/workspaces/ | jq .

curl -s -X POST http://localhost:8000/api/v1/workspaces/ \
  -H "Content-Type: application/json" \
  -d '{"workspace_id":"MABENCH","name":"LongMemEval benchmark","description":"Isolated workspace for agent-memory benchmarks"}'

curl -s http://localhost:8000/api/v1/workspaces/MABENCH | jq .
```

Or:

```bash
python scripts/preflight.py --metronix-url http://localhost:8000 --workspace MABENCH --ensure-workspace
```

> With default Docker install (`AUTH_ENABLED=false`), workspace API needs no token. If auth is enabled, obtain a bearer token via `POST /api/v1/auth/login` first.

## Path A — scripted setup and run (recommended)

Choose commands for your OS:


| OS                   | Setup         | Smoke run          |
| -------------------- | ------------- | ------------------ |
| Linux / macOS        | `./setup.sh`  | `./run.sh --smoke` |
| Windows (PowerShell) | `.\setup.ps1` | `.\run.ps1 -Smoke` |
| Windows (Git Bash)   | `./setup.sh`  | `./run.sh --smoke` |


```bash
# 1. Metronix already running
curl http://localhost:8000/health

# 2. Configure environment (required — see table above)
cd benchmarks/longmemeval
cp .env.benchmark.example .env.benchmark
# Edit .env.benchmark

# 3. One-time setup: venv, datasets, MABENCH workspace
bash ./setup.sh

# 4. Smoke test (~minutes)
bash ./run.sh --smoke

# 5. Full LongMemEval-S (hours/days)
bash ./run.sh

# 6. Monitor (another terminal)
make bench-watch RESULTS=benchmarks/longmemeval/results/<file>.jsonl
```

`bash setup.sh` / `setup.ps1`: create `.venv` → `pip install` → download datasets → `preflight.py --ensure-workspace`.

`run.sh` / `run.ps1`: preflight → `run_benchmark.py` → `evaluate_results.py` → print summary.

**Flags (`run.sh`):**


| Flag                | Description                 |
| ------------------- | --------------------------- |
| `--smoke`           | Oracle variant, 3 questions |
| `--run-only`        | Skip judge evaluation       |
| `--max-questions N` | Limit questions             |
| `--variant oracle   | s`                          |
| `--force`           | Delete output before run    |


PowerShell: `.\run.ps1 -Smoke`, `-RunOnly`, `-MaxQuestions 10`, `-Variant s`, `-Force`.

## Path B — manual step-by-step

### B1. Environment

```bash
cd benchmarks/longmemeval
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-bench.txt
cp .env.benchmark.example .env.benchmark
# Fill .env.benchmark — see Environment variables section
python scripts/preflight.py --check-env-only
```

### B2. Create workspace `MABENCH`

See [Workspace MABENCH](#workspace-mabench) above.

### B3. Preflight

```bash
python scripts/preflight.py --workspace MABENCH
```

### B4. Download dataset

```bash
python scripts/run_benchmark.py download --variant s
# smoke: --variant oracle
```

### B5. Run generation

```bash
python scripts/run_benchmark.py run \
  --variant s \
  --output results/my_run.jsonl \
  --chat-model gpt-4o-mini \
  --chat-base-url https://api.openai.com/v1 \
  --max-questions 10
```

### B6. Monitor

```bash
python scripts/watch_progress.py results/my_run.jsonl --total 500
```

### B7. Evaluate

```bash
python scripts/evaluate_results.py --results results/my_run.jsonl --variant s
# or directly:
python vendor/evaluate_qa.py \
  --results results/my_run.jsonl \
  --reference data/longmemeval_s_cleaned.json \
  --judge-model gpt-4o \
  --judge-base-url https://api.openai.com/v1
```

### B8. Custom models example

```bash
export LME_CHAT_BASE_URL=https://api.deepseek.com/v1
export LME_CHAT_MODEL=deepseek-chat
export LME_CHAT_API_KEY=...

python scripts/run_benchmark.py run --output results/deepseek_run.jsonl
python scripts/evaluate_results.py --results results/deepseek_run.jsonl --variant s
```

## Cross-platform notes


| Action        | Linux / macOS                  | Windows                                 |
| ------------- | ------------------------------ | --------------------------------------- |
| Setup         | `./setup.sh`                   | `.\setup.ps1`                           |
| Run           | `./run.sh`                     | `.\run.ps1`                             |
| Makefile      | `make bench-lme-smoke`         | Use PowerShell scripts                  |
| Activate venv | `source .venv/bin/activate`    | `.venv\Scripts\Activate.ps1`            |
| Python        | `python3` / `.venv/bin/python` | `py -3.11` / `.venv\Scripts\python.exe` |


**All OS:** Docker with Metronix stack, Python 3.11+, Git. Datasets download via Python (no git-lfs).

**Windows:** Prefer PowerShell scripts to avoid CRLF issues with `.sh`. Git Bash works if scripts have LF endings (enforced via `.gitattributes`). Do not use WSL for MCP unless Docker Desktop WSL integration is configured.

**Health check:**

```powershell
Invoke-RestMethod http://localhost:8000/health
```

**Copy MCP key from repo root:**

```powershell
Select-String -Path ..\..\.env -Pattern METRONIX_MCP_API_KEY
```

## Monitoring and results

**During run:** `watch_progress.py` shows `completed/total`, last `question_id`, ETA.

**After evaluate:** accuracy overall and by `question_type` (LongMemEval protocol).

**Artifacts:**


| File                                      | Content                   |
| ----------------------------------------- | ------------------------- |
| `results/<timestamp>_s.jsonl`             | Hypotheses                |
| `results/<timestamp>_s.jsonl.eval-gpt-4o` | Per-question judge labels |


Runs **resume** automatically: existing `question_id` values in the output JSONL are skipped.

## Troubleshooting


| Symptom                          | Windows                                                                                                     | macOS                      | Linux                    |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------- | ------------------------ |
| MCP 401                          | Check `METRONIX_MCP_API_KEY` in `benchmarks/longmemeval/.env.benchmark`                                     | Same                       | Same                     |
| MCP `httpx.ReadError` on Windows | System HTTP proxy intercepts localhost. Fixed in client (`trust_env=False`). Re-run after updating scripts. | Same                       | Same                     |
| Docker not running               | Start Docker Desktop                                                                                        | Docker Desktop / Colima    | `systemctl start docker` |
| `setup.sh: pipefail invalid`     | Use `setup.ps1` or Git Bash + LF scripts                                                                    | —                          | —                        |
| `make: command not found`        | Use `.\run.ps1`                                                                                             | Install make or `./run.sh` | —                        |
| Workspace missing                | `preflight.py --ensure-workspace`                                                                           | Same                       | Same                     |
| Judge errors                     | Check `LME_JUDGE_`* keys and model name                                                                     | Same                       | Same                     |


Full run can take **hours or days** (500 questions × ingest + LLM). Use `--smoke`, `--max-questions`, or `--run-only` for debugging.

Use `--run-only` to test ingest + generation without judge cost.

## Appendix — future benchmarks

This harness targets **LongMemEval-S** only. Possible extensions (not implemented):

- [LoCoMo](https://github.com/snap-research/locomo) — long conversational memory
- [MemoryAgentBench](https://github.com/HUST-AI-Memory/MemoryAgentBench) — multi-benchmark agent memory suite

## References

- Paper: [LongMemEval (ICLR 2025)](https://github.com/xiaowu0162/LongMemEval)
- Dataset: [xiaowu0162/longmemeval-cleaned](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)
- Metronix MCP tools: [docs/MCP_API.md](../MCP_API.md)

