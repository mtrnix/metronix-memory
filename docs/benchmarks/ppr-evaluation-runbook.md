# PPR evaluation runbook (#156)

Use this runbook to produce the frozen flag-off/flag-on evidence required for
issue #156: real-query retrieval quality, LongMemEval, LoCoMo, latency, dataset
identity, effective configuration, and a Take/Park recommendation.

## 1. Rules for a valid comparison

Hold these constant across both legs:

- repository commit and Docker images;
- datasets and their SHA-256 hashes;
- workspace contents, question selection and order;
- answer and judge models, base URLs, prompts, `top_k`, and credentials;
- host, Docker resource limits, and competing workloads.

Change only `METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED`. Use distinct agent-ID
prefixes for each leg so the second run cannot reuse memories written by the
first. Do not publish `.env.benchmark`, API keys, raw private workspace content,
or model-provider request logs.

Run the short smoke pair first. Run the full pair only after both smoke legs
complete without errors. LongMemEval and LoCoMo can incur model charges and can
take hours or days.

## 2. Inventory and start Metronix

From the repository root:

```bash
git rev-parse HEAD
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail --silent --show-error http://localhost:8000/health
```

Record the commit and `docker compose ps` output in the report. Never copy the
contents of `.env` into the report.

### Switch the PPR mode

Set one line in the repository-root `.env`, then recreate only the API service:

```bash
METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED=false
docker compose up -d --build --force-recreate metronix-core
curl --fail --silent --show-error http://localhost:8000/health
```

For the second leg, change the value to `true` and repeat the recreate and
health check. Do not rebuild/reindex the backing stores between legs.

Because the public health endpoint does not expose the effective PPR setting,
the run manifest calls this an **operator-declared** mode. Before each run,
verify the container received the expected value without printing other env:

```bash
docker compose exec metronix-core sh -lc \
  'test "$METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED" = "false"'
```

Use `true` for the flag-on leg. A non-zero exit means stop; do not label the
artifact with that mode.

## 3. LongMemEval dataset and configuration

The repository already provides the official cleaned datasets and scripts.
Downloaded data stays ignored under `benchmarks/longmemeval/data/`.

```bash
cd benchmarks/longmemeval
cp .env.benchmark.example .env.benchmark
```

Edit `.env.benchmark`:

```dotenv
METRONIX_MCP_API_KEY=<copy from repository-root .env>
METRONIX_MCP_URL=http://localhost:8000/mcp
METRONIX_API_URL=http://localhost:8000
LME_WORKSPACE_ID=MABENCH

LME_CHAT_API_KEY=<provider key>
LME_CHAT_BASE_URL=https://api.openai.com/v1
LME_CHAT_MODEL=gpt-4o-mini

LME_JUDGE_API_KEY=<provider key>
LME_JUDGE_BASE_URL=https://api.openai.com/v1
LME_JUDGE_MODEL=gpt-4o

LME_RETRIEVE_TOP_K=10
LME_AGENT_ID_PREFIX=lme-ppr-off
```

Setup and validate without printing secrets:

```bash
./setup.sh
.venv/bin/python scripts/preflight.py --check-env-only
.venv/bin/python scripts/preflight.py --ensure-workspace
shasum -a 256 data/longmemeval_oracle.json data/longmemeval_s_cleaned.json
```

Use the same model identities and dataset hashes for both legs. The official
paper protocol uses GPT-4o as judge; another OpenAI-compatible judge is useful
for internal regression only and must be named in the report.

### LongMemEval smoke pair

With PPR off and `LME_AGENT_ID_PREFIX=lme-ppr-off`:

```bash
./run.sh --smoke --force --output results/ppr-off-smoke.jsonl
```

Enable PPR, recreate/verify `metronix-core`, change only the prefix to
`lme-ppr-on`, then:

```bash
./run.sh --smoke --force --output results/ppr-on-smoke.jsonl
```

### LongMemEval full pair

```bash
# Flag off, prefix lme-ppr-off
./run.sh --variant s --force --output results/ppr-off-full.jsonl

# Flag on, prefix lme-ppr-on
./run.sh --variant s --force --output results/ppr-on-full.jsonl
```

Monitor a running leg from another terminal:

```bash
.venv/bin/python scripts/watch_progress.py results/ppr-off-full.jsonl --total 500
```

Preserve both hypothesis JSONL files and their `.eval-*` judge artifacts.

## 4. LoCoMo dataset and configuration

The LoCoMo runner downloads the official 10-conversation file from a pinned
upstream commit and refuses a checksum mismatch. The upstream license is
CC BY-NC 4.0, so this dataset must not be used commercially.

```bash
cd benchmarks/locomo
cp .env.benchmark.example .env.benchmark
```

Edit `.env.benchmark`:

```dotenv
METRONIX_MCP_API_KEY=<copy from repository-root .env>
METRONIX_MCP_URL=http://localhost:8000/mcp
METRONIX_API_URL=http://localhost:8000
LOCOMO_WORKSPACE_ID=LOCOMO

LOCOMO_CHAT_API_KEY=<provider key>
LOCOMO_CHAT_BASE_URL=https://api.openai.com/v1
LOCOMO_CHAT_MODEL=gpt-4o-mini
LOCOMO_RETRIEVE_TOP_K=10
```

Setup, inspect, and verify:

```bash
./setup.sh
.venv/bin/python scripts/preflight.py --check-env-only
.venv/bin/python scripts/preflight.py --ensure-workspace
.venv/bin/python scripts/run_benchmark.py inspect
```

Expected inventory for the pinned dataset:

| Category | Meaning | Questions |
|---|---|---:|
| 1 | Multi-hop | 282 |
| 2 | Single-hop | 321 |
| 3 | Temporal | 96 |
| 4 | Open-domain | 841 |
| 5 | Adversarial / abstention | 446 |
| **Total** | | **1,986** |

The default run uses categories 1–4 (1,540 questions). Category 5 is opt-in so
the standard answerable score and abstention behavior remain separately visible.
Scoring follows upstream rules: token F1 for categories 2–4, comma-aware
multi-answer F1 for category 1, and abstention phrase accuracy for category 5.

### LoCoMo smoke pair

```bash
# After verifying the server is flag-off:
./run.sh --smoke --retrieval-mode flag-off \
  --output results/ppr-off-smoke.jsonl --force

# After enabling, recreating, and verifying the server is flag-on:
./run.sh --smoke --retrieval-mode flag-on \
  --output results/ppr-on-smoke.jsonl --force
```

The runner automatically uses distinct `locomo-flag-off-*` and
`locomo-flag-on-*` agent IDs.

### LoCoMo full pair

```bash
./run.sh --retrieval-mode flag-off \
  --output results/ppr-off-full.jsonl --force
./run.sh --retrieval-mode flag-on \
  --output results/ppr-on-full.jsonl --force
```

To include abstention:

```bash
./run.sh --categories 1,2,3,4,5 --retrieval-mode flag-off \
  --output results/ppr-off-all.jsonl --force
```

Each result has a manifest and an evaluation report. Treat any non-zero
`error_count` as a failed leg, not as a low score.

## 5. Real-query search suite and latency

Use the same frozen workspace and test set for both modes. The search artifact
now records per-query latency plus mean, p50, p95, and maximum milliseconds.

```bash
# Flag off
.venv/bin/python scripts/run_memory_eval.py \
  --suites search --search-workspace MTRNIX \
  --output results/memory-eval/ppr-off-search.json

# Flag on
.venv/bin/python scripts/run_memory_eval.py \
  --suites search --search-workspace MTRNIX \
  --output results/memory-eval/ppr-on-search.json
```

Do not use a changed or freshly reindexed workspace for only one leg. Inspect
relationship-heavy queries separately as well as overall MRR/NDCG.

## 6. Footprint sampling

### Sample service footprint during each leg

Start the benchmark in one terminal. In another terminal, sample the same
containers at the same interval for both legs:

```bash
mkdir -p results/ppr-footprint
while true; do
  date -u +%Y-%m-%dT%H:%M:%SZ
  docker stats --no-stream --format \
    '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}' \
    metronix-full-api metronix-full-neo4j metronix-full-qdrant
  sleep 5
done | tee results/ppr-footprint/flag-off.tsv
```

Stop sampling when the leg ends and repeat to `flag-on.tsv`. This is sampled
container usage, not an exact allocator-level peak; report the maximum observed
memory and the 5-second sampling interval. Also record persistent store sizes:

```bash
docker system df -v > results/ppr-footprint/docker-system-df.txt
```

Do not claim causality from Docker-wide disk totals when unrelated containers
or images changed between legs.

## 7. Evidence checks before reporting

For every pair confirm:

1. Both legs completed with zero benchmark errors.
2. Git revision, dataset hash, categories, `top_k`, models, and base URLs match.
3. Only retrieval mode and the isolation prefix differ.
4. Question counts match the selected subset.
5. Raw artifacts exist and are retained outside Git.
6. No secrets or private memory content are present in the report.

If any check fails, rerun the pair. Do not average incompatible legs.

## 8. Report template

```markdown
# PPR evaluation report — issue #156

- Date (UTC):
- Repository commit:
- Host / Docker resources:
- PPR implementation parameters: alpha, iterations, tolerance, max nodes, anchors
- Frozen workspace / index identity:

## Configuration parity

| Field | Flag off | Flag on | Match? |
|---|---|---|---|
| Dataset SHA-256 | | | |
| Question count/categories | | | |
| Chat model/base URL | | | |
| Judge model/base URL | | | |
| top_k | | | |
| Agent prefix | ppr-off | ppr-on | Expected difference |

## Results

| Suite / metric | Flag off | Flag on | Delta | Gate |
|---|---:|---:|---:|---|
| Real-query relationship MRR | | | | |
| Real-query relationship NDCG@K | | | | |
| Search latency mean (ms) | | | | |
| Search latency p95 (ms) | | | | |
| LongMemEval accuracy | | | | |
| LoCoMo categories 1–4 score | | | | |
| LoCoMo category 1 multi-hop | | | | |
| LoCoMo category 3 temporal | | | | |
| Error count | | | | Must be 0 |

## Footprint

| Measurement | Flag off | Flag on | Delta |
|---|---:|---:|---:|
| metronix-core max sampled memory (5 s) | | | |
| Neo4j database size | | | |
| Qdrant collection size | | | |

## Verdict

- Decision: Take / Park
- Quality rationale:
- Latency/footprint rationale:
- Known limitations:
- Artifact locations and SHA-256 values:
```

Record the epic's numeric Take/Park thresholds before interpreting the results.
If no threshold exists for a metric, label it informational rather than inventing
a pass criterion.

## 9. Troubleshooting

- `401` from MCP: copy `METRONIX_MCP_API_KEY` from the repository-root `.env`.
- Health check fails: inspect `docker compose ps` and the `metronix-core` logs.
- Workspace missing: rerun the benchmark preflight with `--ensure-workspace`.
- Dataset checksum mismatch: delete only that benchmark's ignored data file and
  rerun its download command; never bypass checksum validation.
- Existing output: use a new path, resume it, or pass `--force` intentionally.
- Provider rate limits: runners retry rate-limit/API failures and keep resumable
  JSONL; investigate remaining `Error:` rows before reporting.
- Scores differ but manifests differ too: the pair is incompatible; align config
  and rerun instead of attributing the delta to PPR.
