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

## Multi-hop graph + dense fusion (opt-in, #497)

All of these default to the previous behaviour. They were evaluated end to end on the
HippoRAG MuSiQue and 2Wiki sets; the methodology, every number and the caveats are in
`benchmarks/musique/findings/2026-09-26-fusion-research-note.md`.

| Setting | Default | What it does |
|---|---|---|
| `METRONIX_RETRIEVAL_FUSION_MODE` | `signal` | final ranking after rerank: `signal` (signal score blended with the min-max cross-encoder score), `rrf`, `calibrated`, `bridge` or `learned` |
| `METRONIX_RETRIEVAL_FUSION_MODEL` | empty | model JSON for `learned`; empty = `src/metronix/retrieval/fusion_models/default.json` |
| `METRONIX_RETRIEVAL_FUSION_WEIGHTS` | empty | per-channel weights for `rrf` / `calibrated` / `bridge`, e.g. `rerank=1,dense=0` |
| `METRONIX_RETRIEVAL_GRAPH_PPR_SUBGRAPH` | `paths` | `specific` grows the PPR subgraph from the least-mentioned seed entities, skipping hubs |
| `METRONIX_RETRIEVAL_GRAPH_PPR_MAX_DOCS` / `_HUB_CAP` | 100 / 200 | budget of the `specific` subgraph |
| `METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT` | `subgraph` | `seeds` teleports to the seed entities; `ranked` weights them by the dense rank of the anchors that mention them |
| `METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT_RANK_POWER` | 1.0 | exponent of the `ranked` weights |

The configuration measured best for multi-hop questions:

```bash
METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED=true
METRONIX_RETRIEVAL_GRAPH_PPR_EXCLUDE_DENSE_ANCHORS=true
METRONIX_RETRIEVAL_GRAPH_PPR_SUBGRAPH=specific
METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT=ranked
METRONIX_RETRIEVAL_FUSION_MODE=learned
```

The two PPR settings are not one switch; what each contributes depends on the size of
the workspace graph (note §5.11):

- `TELEPORT=ranked` helped on both graphs measured. On a 535-passage graph it carried
  the whole gain: +8.3 R@5 on its own, with `SUBGRAPH=specific` adding almost nothing.
- `SUBGRAPH=specific` matters only where the production (`paths`) subgraph gets cut. It
  is cut at `MAX_NODES * 8` edges in the database's traversal order, not by relevance.
  - How often that happened: never on the 535-passage graph (0 of 30 queries); on the
    11,656-passage graph in 74 of 100 queries with one anchor and 100 of 100 with five.
  - On the large graph neither setting was enough alone: next hop in the channel's top
    5 for 14 of 1,000 questions in production, 42 with the seed teleport alone, 21 with
    `specific` alone, 192 with both.
  - On the small graph `specific` changed no top 5, so turning it on there is harmless
    but buys nothing.
- To see which case a workspace is in, count `graph_ppr.subgraph_truncated` log events
  (logged at info by the production subgraph). Rare events mean `specific` will not
  change results; frequent events mean it should be on.

The shipped `learned` model was fitted on benchmark questions (Wikipedia paragraphs),
not on a Metronix workspace. Before enabling it for a workspace, run `make eval-compare`
as above; `calibrated` is the fixed-weight alternative that needs no model.
