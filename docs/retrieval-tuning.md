# Retrieval Tuning

How the hybrid retrieval fusion knobs work, why some are off by default, and
how to measure a change before you keep it.

## The knobs

Set in `.env` (or in `src/metronix/core/config.py`, class `Settings`, section
"Retrieval tuning"). Every value below is the current default.

| Setting | Default | What it does |
|---|---|---|
| `embedding_dim` | 768 | dimension of the dense embedding vectors |
| `rrf_k` | 60 | standard RRF smoothing constant for rank fusion |
| `ADAPTIVE_RRF_ENABLED` | `false` | switch rank fusion from fixed `rrf_k` to overlap-adaptive `rrf_k_low`/`rrf_k_high` |
| `RRF_K_LOW` / `RRF_K_HIGH` | 20 / 80 | the adaptive endpoints |
| `RRF_OVERLAP_THRESHOLD_LOW` / `_HIGH` | 0.2 / 0.7 | overlap thresholds that pick where between the endpoints the effective k lands |
| `dense_weight` | 0.35 | weight of the dense (vector) channel |
| `sparse_weight` | 0.0 | weight of the sparse (keyword) channel; off |
| `graph_weight` | 0.15 | weight of the graph (PPR) channel |
| `metadata_weight` | 0.20 | weight of metadata matches |

## Why ADAPTIVE_RRF_ENABLED is off

Adaptive RRF was introduced in MTRNIX-211 with the flag on. Commit `3bdb614`
(2026-03-31) turned it off because it regressed MRR and NDCG on the eval test
set of that time: the fixed `rrf_k=60` ranked better overall. The flag was
kept because the idea is sound and may win once the eval set grows; it just
loses today. The one-line note in `.env.example`
("adaptive RRF fusion (regresses metrics, off)") is all that survived of that
decision in the tree, and this section is the full story.

If you turn it on, expect MRR/NDCG to drop unless your query mix has much
higher dense/sparse channel overlap than the current test set. Re-run the eval
and compare before trusting it.

## How to measure a change

The eval test set is a YAML set of 48 labeled queries with ground-truth
`doc_labels`, scored with three deterministic metrics (no LLM calls):
Precision@K, MRR, NDCG@K. See `docs/eval-test-set.md` for the tool itself.

```bash
make eval              # run the stable queries
make eval-compare      # run and diff against the last saved run
```

Workflow for any fusion-knob change:

1. `make eval-save` on the current defaults to pin the baseline.
2. Change one knob in `.env`, restart the API service.
3. `make eval-compare` and read the MRR/NDCG delta. Keep the change only if
   the metrics improve on the stable query set.

The same discipline applies at benchmark scale. The PPR evaluation runbook
(`docs/benchmarks/ppr-evaluation-runbook.md`) fixes everything except one
flag per comparison leg, so a regression is attributable to the flag and not
to drift in datasets, models, or host state. Use it when a change survives
the fast eval loop and you need frozen flag-off/flag-on evidence.
