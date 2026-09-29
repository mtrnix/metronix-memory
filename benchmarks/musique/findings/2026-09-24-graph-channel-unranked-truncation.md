# Graph channel: unranked truncation in `search_by_doc_labels` (addendum to #497)

Date: 2026-09-24. Status: **observation only, no code change.** Measured with the #508
fix applied (branch `fix/508-graph-relationship-projection`) and paragraph
deduplication in the MuSiQue converter.

## Summary

`recall_graph` / `recall_graph_async` collect every doc label reached by BFS into an
unordered `set`, then take the first `recall_top_n_graph` (default 5) points that
`search_by_doc_labels` returns. That call is a Qdrant `scroll` with a payload filter,
so points come back **in ascending point-ID order** (random UUIDs), and every hit gets
a constant **score `1.0`**. Which BFS results survive the cut is therefore unrelated
to hop distance or relevance, and the graph channel hands the fusion step flat
scores in arbitrary order.

## Code path

| Step | Location | Behaviour |
| --- | --- | --- |
| BFS result | `src/metronix/retrieval/channels.py:789-812` (sync), `:883-906` (async) | `all_labels: set[str]` — hop depth is discarded |
| Fetch + cut | `channels.py:820` / `:914` | `store.search_by_doc_labels(list(all_labels), limit=limit)` then `hits[:limit]` |
| Store | `src/metronix/storage/qdrant.py:460-485` (sync), `:973-999` (async) | `client.scroll(filter doc_label IN …, limit)`; `_format_result(p, 1.0)` |
| Limit | `src/metronix/core/config.py:200` | `recall_top_n_graph = 5` (`RECALL_TOP_N_GRAPH`) |
| Fusion input | `channels.py:122` `merge_channels` | sorts merged results by max channel score; graph contributes `1.0` for each of its ≤5 hits |

By contrast, the opt-in PPR channel (`recall_graph_ppr_async`, `channels.py:653`)
sorts hits by PPR score before cutting and assigns that score, so the problem is
specific to the BFS graph channel.

## Measurement

Setup: MuSiQue-Ans dev, first 150 answerable 2-hop questions
(`benchmarks/musique/data/`), oracle graph, 2328 distinct paragraphs (250 supporting)
in workspace `musique-dev`. Neo4j 5.26 Community + Qdrant 1.18.0 (versions from
`docker-compose.yml`), run in a cloud container. Qdrant points carry the converter's
payload with a constant dense vector (no embedding service); the graph channel only
filters by `doc_label`, so vectors do not affect it. Probe:
`python -m benchmarks.musique.scripts.probe --limit 150 --max-depth 2 --recall`.
Raw rows: `benchmarks/musique/results/2026-09-24/`.

### BFS vs. what `recall_graph` returns

| | oracle seeds | `extract_title_entities` seeds |
| --- | --- | --- |
| Questions with ≥1 BFS label | 150 | 60 (47 no seed, 43 seed not in graph) |
| Last-hop gold reached via BFS (hop ≥ 1) | 145 | 60 |
| BFS labels per question, median / max | 2 / 8 | 2 / 6 |
| Questions with > 5 BFS labels (cut applies) | 15 | 1 |
| Hop-0 gold in `recall_graph` output | 148 | 60 |
| Last-hop gold in `recall_graph` output | 147 | 60 |
| Both gold in output | 145 | 60 |
| **Questions where BFS found gold but the cut dropped it** | **5 of 15 cut** | 0 of 1 |
| Dropped gold labels by hop found | hop 0: 4, hop 1: 1 | — |

Label distribution (oracle): 2→76, 3→11, 4→44, 5→4, 6→10, 7→1, 8→4 questions.
When the cut applies, gold is lost in 5/15 = 33% of questions.

Control, same data with `graph_ops.py` from before #508 (bare `RETURN r`):
0/150 last-hop via BFS, 5/150 all gold found — BFS never expands.

### Worked example

"When did the person who first brought a postal service into Umayyad lands become
caliph?" — oracle seed `Umayyad Caliphate`, 8 BFS labels, both gold at hop 0.
`search_by_doc_labels` order (point ID ascending) and the cut at 5:

| # | label | point id | gold | kept |
| --- | --- | --- | --- | --- |
| 1 | `…9fc6604f` | `10589e51…` | | yes |
| 2 | `…efaa8596` | `17c91e47…` | | yes |
| 3 | `…0000c603` | `28c7a59c…` | **gold** | yes |
| 4 | `…aea2b84c` | `41aef69b…` | | yes |
| 5 | `…57c630a7` | `49207ca6…` | | yes |
| 6 | `…0edd084f` | `72528ef7…` | **gold** | **dropped** |
| 7 | `…31881472` | `93aa6d17…` | | dropped |
| 8 | `…327ff2bc` | `c6fbe025…` | | dropped |

All five kept hits carry `score = 1.0`.

## Why this matters for #497

- The graph channel's contribution to fusion is a constant `1.0` on ≤5 chunks picked
  by UUID order. `merge_channels` sorts by max channel score, and the dense channel
  emits RRF hybrid scores (`recall_dense`, `channels.py:258`); unless those reach
  1.0, graph hits sort at the top of the merged list regardless of relevance, tied
  with other constant-1.0 scroll channels (exact/metadata also use
  `_format_result(p, 1.0)`). Neither the dense score range nor whether the later
  multi-signal scoring in `search.py` (after line 1233) corrects the ordering was
  traced here; both are the next check against the #497 score-fusion analysis.
- The effect was invisible in earlier corpora because BFS never expanded (#508), so
  the channel returned at most the seeds' direct documents.
- On this corpus the cut rarely binds (median 2 labels) because the oracle graph is
  sparse. With LLM-extracted graphs (denser MENTIONS/RELATION fan-out) the label set
  per query will be larger and the arbitrary cut will bind far more often.
- Secondary: `limit` counts Qdrant points, not labels, so a document split into
  several chunks consumes several slots; and `_post_filter_acl` runs after the
  scroll limit, so ACL filtering can shrink the result below 5 without refilling.

## Candidate directions (not implemented)

1. Keep hop depth from BFS (`dict[label, hop]` instead of `set`) and order/score by
   it, e.g. `score = decay ** hop`.
2. Fetch all BFS labels, then rank (hop depth, then dense similarity to the query or
   entity mention count) before cutting.
3. Emit a graded channel score instead of `1.0` so fusion can weigh graph evidence.

Any of these changes production retrieval and should be decided within #497.
