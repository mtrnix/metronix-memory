# LongMemEval-S Benchmark (Metronix)

Run the [LongMemEval-S](https://github.com/xiaowu0162/LongMemEval) agent-memory benchmark against Metronix MCP memory.

**Full guide:** [`docs/benchmarks/longmemeval.md`](../../docs/benchmarks/longmemeval.md)

## Configuration file

Benchmark settings live in **`benchmarks/longmemeval/.env.benchmark`** — not the repo-root `.env` used by Docker.

```bash
cd benchmarks/longmemeval
cp .env.benchmark.example .env.benchmark
# Edit .env.benchmark
```

Repo-root `.env` is only used as a fallback for `METRONIX_MCP_API_KEY` (from `install.sh`).

**MCP URL:** default `METRONIX_MCP_URL=http://localhost:8000/mcp` — the **`metronix-full-api`** container (`metronix-core` in Compose), port **8000**, path **`/mcp`**. From Docker network: `http://metronix-core:8000/mcp`.

## Prerequisites

- Metronix stack running (`http://localhost:8000/health`)
- Python 3.11+
- LLM API keys (OpenAI-compatible) for chat + judge in `.env.benchmark`

## Quick start

| OS | Setup | Smoke run |
|----|-------|-----------|
| Linux / macOS | `./setup.sh` | `./run.sh --smoke` |
| **Windows (PowerShell)** | `.\setup.ps1` | **`.\run.ps1 -Smoke`** |
| Windows (Git Bash) | `./setup.sh` | `./run.sh --smoke` |

> **Windows PowerShell:** `./run.sh` does not run bash scripts. Use **`.\run.ps1 -Smoke`** instead.

```bash
cd benchmarks/longmemeval
cp .env.benchmark.example .env.benchmark
# Edit .env.benchmark — at minimum:
#   METRONIX_MCP_API_KEY  (or leave blank if set in repo-root .env)
#   LME_CHAT_API_KEY
#   LME_JUDGE_API_KEY     (can match chat key)

./setup.sh
./run.sh --smoke      # oracle variant, 3 questions
./run.sh              # full LongMemEval-S + judge
```

## Monitor progress

```bash
.venv/bin/python scripts/watch_progress.py results/<file>.jsonl --total 500
```

From repo root (Linux/macOS):

```bash
make bench-watch RESULTS=benchmarks/longmemeval/results/latest.jsonl
```

## Manual mode

See Path B in [`docs/benchmarks/longmemeval.md`](../../docs/benchmarks/longmemeval.md).

## Artifacts

| Path | Description |
|------|-------------|
| `results/*.jsonl` | Generated hypotheses (`question_id`, `hypothesis`) |
| `results/*.jsonl.eval-*` | Judge output with per-question labels |
| `data/` | Downloaded LongMemEval datasets |

## Makefile targets (Linux / macOS, from repo root)

```bash
make bench-lme-setup
make bench-lme-smoke
make bench-lme
make bench-watch RESULTS=benchmarks/longmemeval/results/<file>.jsonl
```

Windows: use `.\setup.ps1` / `.\run.ps1` instead of `make`.
