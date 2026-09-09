# LoCoMo benchmark for Metronix

This runner evaluates Metronix retrieval and answer generation on the official
[LoCoMo](https://github.com/snap-research/locomo) QA annotations.

The dataset is pinned to upstream commit
`3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376` and verified with SHA-256
`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
LoCoMo data is CC BY-NC 4.0: use it only for non-commercial evaluation, retain
attribution, and indicate modifications.

## Quick start

```bash
cd benchmarks/locomo
cp .env.benchmark.example .env.benchmark
# Add METRONIX_MCP_API_KEY and LOCOMO_CHAT_API_KEY.
./setup.sh
./run.sh --smoke --retrieval-mode flag-off
```

The default subset is categories 1–4 (1,540 answerable questions). Add category
5 explicitly when abstention behavior is part of the gate:

```bash
./run.sh --categories 1,2,3,4,5 --retrieval-mode flag-off
```

Artifacts are written under `results/`:

- `*.jsonl`: answers, ground truth, category, retrieval count, per-question
  `recall_at_5` / `recall_at_10` (evidence session vs. retrieved), and split
  latency (`ingest_ms` / `search_ms` / `answer_ms` / `total_ms`).
- `*.jsonl.manifest.json`: pinned dataset + sha256, Git revision + dirty flag,
  the question-set digest (`question_ids_sha256`), model, workspace, `top_k`,
  categories, sanitized MCP endpoint, and operator-confirmed retrieval mode.
- `*.jsonl.query_set.json`: the exact ordered `question_id` list the run ran.
- `*.jsonl.eval.json`: aggregated **recall@10 / recall@5** (the retrieval gate,
  overall + per-category), per-phase latency (p50/p95/max), and official
  per-category token-F1. Category 5 (abstention) is excluded from the recall
  aggregate.

For the complete PPR flag-off/on procedure and report template, see
[`docs/benchmarks/ppr-evaluation-runbook.md`](../../docs/benchmarks/ppr-evaluation-runbook.md).
