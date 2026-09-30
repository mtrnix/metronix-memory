# Graph + dense fusion for multi-hop retrieval (#497): research note

Date: 2026-09-26/27. Continues `2026-09-26-fusion-handoff.md` (earlier session).
Status: end-to-end evaluation done on the HippoRAG MuSiQue set (1,000 questions, the
Llama-3.3-70B OpenIE graph HippoRAG 2 released; tune half / held-out confirm half) and on
the HippoRAG 2Wiki set (1,000 questions, all held out, a title-mention graph), with the
production pipeline. The protocol and its two amendments were committed before the runs
they govern (git history of this file). The oracle-graph dev slice and the qwen2.5:3b
graph slice are in §5.10.

## Summary

1. **The graph channel, not the fusion formula, was the first bottleneck on real
   graphs.** On the OpenIE graph the production PPR channel puts the next-hop passage in
   its top 5 for 14 of 1,000 questions even when given the right anchor (the oracle
   graph: 150 of 150, which is why it went unnoticed). A bounded subgraph grown from the
   most specific seed entities and a teleport weighted towards the best dense anchors
   (opt-in, "ppr+") raise that to 192, at lower latency, and raise the share of gold
   passages in the reranker's pool from 75.2% to 80.9% (MuSiQue) and from 79.8% to 97.4%
   (2Wiki). The production channels add almost nothing to the pool (graph-only gold
   passages: PPR 0 and BFS 1 on 500 MuSiQue questions, BFS 3 on 1,000 2Wiki questions).
2. **The production fusion then buries what the graph finds.** With "ppr+" under the
   production `signal` blend R@5 moves by +0.6 (MuSiQue) and +1.6 (2Wiki).
3. **Fixing the blend alone helps a little, and replicates.** The pre-registered winner
   of the tune half, `calibrated` fusion without graph, beats production on the held-out
   MuSiQue half by +1.75 R@5 (CI 0.3 to 3.2, p = 0.018) and on 2Wiki by +0.7 (p = 0.076);
   most of that is the cross-encoder no longer being min-max-squashed.
4. **A learned fusion extracts the graph's signal, and transfers.** A logistic regression
   over 20 per-candidate features (cross-encoder, channel scores and ranks, query-level
   confidence), fitted on the 500 MuSiQue tune questions, run by the production pipeline:
   - MuSiQue held-out half: R@5 58.3 → **62.8** (+4.5, CI 2.8 to 6.2, 86 wins / 31
     losses), both gold passages in the answer context 44.4% → 57.8%; +2.2 R@5 over the
     same learned fusion without the graph (p = 0.007).
   - 2Wiki, a different dataset and graph, never used for fitting: R@5 71.9 → **85.7**
     (+13.8, 338 / 9), R@2 +6.0, both gold passages in context 55.2% → 89.7%; +13.0 R@5
     over the learned fusion without the graph.
   - Metronix's own qwen2.5:3b graph, 30 dev questions (a consistency check, too small
     to size the effect): R@5 65.0 → 78.3 (`learned`) / 80.0 (`calibrated`), the last
     hop in the top 5 10 → 19 / 18 of 30 (§5.10).
5. **Against published systems** this is not a new state of the art: HippoRAG 2 reaches
   74.7 / 90.4 R@5 with a 7B embedder, and our 137M first stage caps MuSiQue. The gain of
   graph fusion over the same system without it (+2.2 / +13.0; +4.5 / +13.8 over
   production) is of the same order as HippoRAG 2's over NV-Embed-v2 (+5.0 / +13.9).
6. **Negative results**: `rrf` with equal votes hurts R@2 badly once the graph channel is
   noisy (-9.8 on MuSiQue tune); chain-conditioned `bridge` scoring was worse than plain
   `calibrated` on the questions it finished (stopped for futility); query-conditioned
   hand features add little over static ones; on the oracle graph every fusion looks
   excellent because the topology leaks the answer.
7. Four scaling defects surfaced on the way (§5.9), one of them fixed here without
   changing results: `get_doc_labels_by_entities` ran one full node scan per document
   (up to 31 s per call; the default BFS channel took ~20 s per question).

## 1. Question

Issue #497: the PPR graph channel found the bridge (last-hop) paragraph for 135 of 150
MuSiQue questions, yet it rarely reached the answer model's context. The earlier session
traced the loss to the final score (`0.6 * signal + 0.4 * minmax(ce)` in the `mixed`
profile gives a graph-only candidate a signal score of 0, and min-max of the skewed
cross-encoder probabilities leaves the tail to that signal score) and implemented three
opt-in fusion modes. The open question is whether any of them improves multi-hop
passage recall on a graph that was not built from the gold decompositions, by how much
relative to published systems, and whether it holds on held-out questions.

## 2. Approaches considered

| Approach | Idea | Fit for Metronix | Used here |
| --- | --- | --- | --- |
| HippoRAG 2 (arXiv 2502.14802) | Fusion inside the walk: passage nodes carry dense scores in the reset vector, query-to-triple seeding with an LLM filter, PPR output is the ranking | Needs triple embeddings, one LLM call per query and PPR over the full graph; the teleport-on-seeds part transfers cheaply | Seed teleport (§3.2); its published numbers as reference |
| Weighted RRF (Cormack et al. 2009) | Rank-level fusion; no scale calibration needed | Drop-in after rerank | `rrf` |
| Calibrated convex combination (Bruch et al., TOIS 2023, TM2C2); PhaseGraph (arXiv 2603.28886) | Normalise each channel, then mix linearly. PhaseGraph maps PPR and dense scores through a percentile transform and reports +1.4 pp held-out last-hop@5 on MuSiQue (75.1 → 76.5, 8 wins / 1 loss) | Drop-in; on a pool of about 35 candidates a percentile transform is close to a rank transform, i.e. to `rrf` | `calibrated` (max-normalisation, raw cross-encoder probability) |
| Query-conditioned weights: DAT (arXiv 2503.23013), MoR (EMNLP 2025), RegimeRouter (arXiv 2604.09019) | Per-query channel weights: an LLM judges each retriever's top hit (DAT); training-free confidence signals (MoR); a five-feature surface-text router that decides whether hop 2 is named in the question or only in the bridge passage (RegimeRouter, significant on MuSiQue, p = 0.002) | DAT costs an LLM call per query; MoR needs corpus clustering; RegimeRouter's features are cheap but it is trained | Offline only (`fusion_learned.py --features query`), as a headroom check |
| Chain- or bridge-conditioned scoring: MDR, PathRetriever, Beam Retrieval; BridgeRAG (arXiv 2604.03384) | Score a candidate conditioned on the passage that leads to it. BridgeRAG scores (question, bridge, candidate) with an LLM judge and reports R@5 81.5 on the HippoRAG MuSiQue set (+6.8 pp over HippoRAG 2) | Zero-shot with the existing cross-encoder: `P(anchor) * P(candidate | question + anchor)` | `bridge` |
| GFM-RAG (graph foundation model retriever) | GNN trained on KG-QA pairs | Needs training and a GPU | Not used |
| GraphRAG local search | Fixed context shares per source | Trivial, crude | Not used |

Published passage recall on the HippoRAG MuSiQue set (1,000 questions, 11,656 passages)
and 2Wiki set (1,000 questions, 6,119 passages):

| System | MuSiQue R@2 | MuSiQue R@5 | 2Wiki R@5 |
| --- | --- | --- | --- |
| Contriever | 34.8 | 46.6 | 57.5 |
| ColBERTv2 | 37.9 | 49.2 | — |
| HippoRAG (ColBERTv2) | 40.9 | 51.9 | 89.1 |
| NV-Embed-v2 (7B) | — | 69.7 | 76.5 |
| HippoRAG 2 (NV-Embed-v2 + Llama-3.3-70B) | — | 74.7 | 90.4 |
| PropRAG | — | 78.3 | — |
| BridgeRAG (LLM judge) | — | 81.5 | 95.3 |

The comparable quantity for Metronix is the gain of a graph method over **its own**
dense retriever (HippoRAG 2: +5.0 R@5 on MuSiQue, +13.9 on 2Wiki), because
nomic-embed-text (137M) is far weaker than NV-Embed-v2, while bge-reranker-v2-m3 is a
stronger second stage than anything in those pipelines.

## 3. What is implemented (all opt-in; defaults unchanged)

### 3.1 Fusion modes (`METRONIX_RETRIEVAL_FUSION_MODE`), from the handoff

| Mode | Final score | Rerank pool |
| --- | --- | --- |
| `signal` (default) | `blend * signal + (1 - blend) * minmax(ce)` | top by signal score |
| `rrf` | `sum_c w_c / (60 + rank_c)` over cross-encoder, dense, graph, metadata rankings; one vote each | top by channel RRF |
| `calibrated` | `0.5 * P_ce + 0.25 * dense/max + 0.25 * graph/max` | top by channel RRF |
| `bridge` | `calibrated`, with each graph candidate's cross-encoder score replaced by `max(P_ce, P(anchor) * P(cand | q + anchor))`, anchor = best of the top-3 cross-encoder passages sharing an entity with it | top by channel RRF |
| `learned` (added in this session, §5.6) | linear score of a logistic regression over 20 features per candidate: cross-encoder log-odds and reciprocal rank; dense and graph scores (pool-max normalised), reciprocal ranks and presence flags; and the top cross-encoder probability, its margin over the second and the graph channel's share of mass on its top candidate, each multiplied into the dense and graph features. Model file: `METRONIX_RETRIEVAL_FUSION_MODEL`, default `src/metronix/retrieval/fusion_models/default.json`, fitted on the MuSiQue tune half with "ppr+"; falls back to `calibrated` if no model loads | top by channel RRF |

Weights of `rrf`, `calibrated` and `bridge` were fixed before any measurement and are not
tuned in this note. `learned` is fitted on the tune half only; the features are computed
by one function (`metronix.retrieval.fusion.learned_features`) for both fitting and
serving, and the online pipeline reproduces the offline held-out numbers (R@5 62.80
online vs 62.73 offline on the confirm half; the small difference comes from 2 questions
with more than 35 candidates, where the online pool is chosen by channel RRF).

### 3.2 PPR channel settings (new in this session)

| Setting | Values | Effect |
| --- | --- | --- |
| `METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT` | `subgraph` (default), `seeds`, `ranked` | teleport uniform over the subgraph's entities; uniform over the seed entities; or seeds weighted by the dense rank of the anchors mentioning them (sum of `1 / rank ** power`, `_TELEPORT_RANK_POWER` = 1; query-named entities weigh 1), a cheap form of HippoRAG 2's dense-weighted reset vector |
| `METRONIX_RETRIEVAL_GRAPH_PPR_SUBGRAPH` | `paths` (default), `specific` | `get_ppr_subgraph` (two-hop expansion cut at `MAX_NODES * 8` edges in traversal order) or `get_ppr_subgraph_specific` (documents of the least-mentioned seeds first, seeds above `HUB_CAP` skipped, up to `MAX_DOCS`) |
| `METRONIX_RETRIEVAL_GRAPH_PPR_MAX_DOCS`, `_HUB_CAP` | 100, 200 | budget of `specific` |

The `specific` budget (100 documents, hub cap 200) was chosen in an offline simulation
on the whole 1,000-question set with the gold anchor: it came within 8 questions of PPR
over the entire graph there (399 vs 407 in the top 5; 300 or 1,000 documents gave
398-400, hub cap 50 gave 392). That choice has therefore seen the
confirmation questions of §4, but only through a channel-only probe with gold anchors;
the end-to-end comparison is still held out.

### 3.3 Harness

- `hipporag_set.py`: loads the HippoRAG MuSiQue set with the released OpenIE graph, and
  now also the 2Wiki set (`--dataset 2wikimultihopqa`) with a title-mention graph
  (`--graph titles`: a passage mentions its own title and every corpus title in its
  text; no LLM, no annotations). Passages are stored as `title\ntext`, the string
  HippoRAG indexes and matches gold against.
- `ppr_ceiling.py`: the channel probe of §5.3. It needs only the graph, not vectors.
- `pipeline_probe.py`, `fusion_replay.py`, `fusion_learned.py`, `compare_runs.py`,
  `run_matrix.sh`: unchanged from the handoff.

## 4. Evaluation protocol (fixed before any end-to-end run)

Data: HippoRAG MuSiQue-1000 (Llama-3.3-70B OpenIE graph), then HippoRAG 2Wiki-1000
(title-mention graph). Split by question index parity: even = tune (500), odd = confirm
(500). The 66 MuSiQue questions shared with the 150-question dev slice are reported
separately (`compare_runs.py --exclude`).

"ppr+" is the PPR channel with `SUBGRAPH=specific`, `TELEPORT=ranked` (power 1) and
`EXCLUDE_DENSE_ANCHORS=true`. The teleport was chosen before any end-to-end run, by the
tune-half pool coverage of the BM25 proxy (§5.4: 69.4 for `ranked` vs 65.6 for `seeds`);
the rank power was left at its default of 1 (power 2 gave 69.9 vs 69.4 on the tune half
in an exploratory run, not a meaningful difference).

**Phase 1, tune half only**, each a `pipeline_probe` run (`k = 25`, query expansion and
classifier off, cross-encoder on unless stated):

- dense only: `off:signal` with `RERANKER_ENABLED=false` (hybrid dense + SPLADE; our
  first stage against Contriever / NV-Embed-v2);
- production fusion: `off`, `bfs` (production default), `ppr`, `ppr-novel` under `signal`;
- `rrf` under `off`, `bfs`, `ppr`, `ppr-novel`; `calibrated` under `off`, `ppr`,
  `ppr-novel`; `bridge` under `ppr`, `ppr-novel`;
- "ppr+" under `signal`, `rrf`, `calibrated`, `bridge`;
- cross-encoder only (`rrf` with weights `rerank=1,dense=0,graph=0,metadata=0`) under
  `off` and "ppr+": the controls for "gain from fixing the blend alone".

Weights are the mode defaults fixed in the handoff; nothing is tuned.

**Selection**: the configuration with the highest tune-half R@5.

**Phase 2, confirm half**: the selected configuration, `bfs:signal` (production
default), `ppr:signal`, the selected fusion without graph (`off`), both cross-encoder-only
controls and dense only. Paired per question: bootstrap 95% CI and exact sign test
(`compare_runs.py`), overall and per hop count (2/3/4).

**Amendment, fixed after the tune half and before any confirm-half run** (commit
timestamp): the tune half showed the graph helping the answer context (both gold passages
in the top 25) far more than R@5, and a cross-validated learned fusion with "ppr+"
beating every hand-set fusion. Two secondary hypotheses are therefore added for the
confirm half, and one deviation recorded:

- H2: "ppr+" vs no graph under the same fusion (`calibrated`) on *both gold passages in
  the answer context* (the "gold in `fragments`" metric of the task).
- H3: learned fusion (logistic regression, `fusion_learned.py`, feature set chosen by
  tune-half 5-fold CV R@5: `query`, 64.9 vs `static` 64.3), fitted on all tune-half
  questions of the "ppr+" `signal` dump and applied unchanged to the confirm half,
  against the selected hand-set configuration and against the same learned fusion
  without graph (fitted on `off:signal`).
- Deviation: `ppr:bridge` and `ppr-novel:bridge` were not run. The production PPR
  channels add no graph-only gold passage to the candidate pool on this graph
  (tune half: 0), so `bridge` could only re-score non-gold candidates, and each run
  costs about 5 hours of CPU (the conditional cross-encoder pairs are 3-4x longer).
  "ppr+" `bridge` was run.

**2Wiki (fixed before any 2Wiki end-to-end run)**: no selection on 2Wiki. All 1,000
questions are held out with respect to the MuSiQue selection and are used to test
transfer: first stage only, `off:signal`, `bfs:signal`, `off:calibrated`, "ppr+" under
`signal`, `calibrated` and cross-encoder only, the no-graph cross-encoder-only control,
and the MuSiQue-selected configuration if it is not among these. "ppr+" on 2Wiki uses
the title-mention graph with the same settings (`specific`, `ranked`, anchors
excluded). Primary comparison: MuSiQue-selected configuration vs `bfs:signal` on R@5.

**PR criterion** (#497): the selected configuration beats `bfs:signal` on the confirm
half with sign-test p < 0.05 on R@5, beats its own `off` control (the graph contributes),
and does not lose to the cross-encoder-only control on the same channel.

## 5. Results

### 5.1 Oracle graph, 150 questions (earlier session)

See the handoff, §2. In short: graph-only last-hop candidates were dropped by the blend
(34 of 44), `rrf` recovers them (both gold paragraphs in context 105 → 140 with PPR),
but the oracle topology leaks gold (92% of distractors isolated), so those gains cannot
be attributed to fusion.

### 5.2 Is a non-oracle graph fair?

| Graph | passages | gold: entities / neighbours / isolated | distractors: entities / neighbours / isolated |
| --- | --- | --- | --- |
| MuSiQue oracle (dev 150) | 2,328 | 2.45 / 1.8 / 0% | 1.00 / 0.18 / 92% |
| MuSiQue OpenIE, Llama-3.3-70B (HippoRAG 2) | 11,656 | 12.5 / 301 / 0.3% | 11.9 / 341 / 1.7% |
| 2Wiki title-mention (this session) | 6,119 | 1.75 / 11.0 / 14.7% | 1.44 / 10.1 / 60.1% |

"Neighbours" are passages sharing at least one entity. The OpenIE graph is balanced. The
title-mention graph is not: 2Wiki was built from Wikidata relations between the gold
entities, so gold passages name each other's titles far more often than distractors do.
That is a property of the text, not of annotations, and HippoRAG's 2Wiki graph shares
it, but 2Wiki results on this graph favour graph methods for that reason.

### 5.3 The PPR channel on real graphs, with known anchors (`ppr_ceiling.py`)

Hop-1 gold passage in the channel's top 5 (anchors excluded). "1 anchor" = gold hop-0
passage only; "5 anchors" = gold hop-0 plus four of the question's distractors, a proxy
for the dense top 5 (the real dense top 5 contains hop 0 for 143 of 150 dev questions).

MuSiQue, HippoRAG set, OpenIE graph, 1,000 questions:

| Subgraph | Teleport | anchors | next hop in subgraph | @1 | @5 | @30 | latency median / p90 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `paths` (production) | `subgraph` (production) | 1 | 415 | 24 | 112 | 351 | 125 / 155 ms |
| `paths` | `seeds` | 1 | 415 | 90 | 231 | 399 | 128 / 153 ms |
| `specific` | `subgraph` | 1 | 770 | 22 | 123 | 414 | 57 / 89 ms |
| `specific` | `seeds` | 1 | 770 | 137 | **399** | 683 | 57 / 86 ms |
| `paths` (production) | `subgraph` (production) | 5 | 67 | 2 | 14 | 51 | 135 / 170 ms |
| `paths` | `seeds` | 5 | 67 | 20 | 42 | 64 | 147 / 189 ms |
| `specific` | `subgraph` | 5 | 737 | 2 | 21 | 176 | 93 / 116 ms |
| `specific` | `seeds` | 5 | 737 | 44 | **192** | 549 | 93 / 119 ms |

The two settings need each other: with five anchors each alone moves the top-5 count
from 14 to 42 or 21, both together to 192. The production subgraph does not even load
the next hop for 933 of 1,000 questions once five anchors' worth of seeds (57 on
average) compete for its 500 nodes.

Next hop shares at least one entity with the gold anchor in the OpenIE graph for 823 of
1,000 questions (888 with the four extra anchors); that bounds any one-entity-hop walk.
PPR over the whole graph (scipy, seed teleport, gold anchor) gives 407 in the top 5;
damping 0.5 instead of 0.85 or IDF-weighted seeds change it by at most 7.

Other graphs, 5 anchors:

| Graph | questions | production (`paths`, `subgraph`) | `paths`, `seeds` | `specific`, `seeds` |
| --- | --- | --- | --- | --- |
| MuSiQue oracle (dev) | 150 | 150 | 150 | 150 |
| 2Wiki title-mention, compositional + inference 2-hop | 521 | 305 | 447 | 480 |

On the oracle graph the median subgraph holds 2 passages, so every variant is perfect;
the problem is invisible there. On the sparse title graph the teleport matters and the
subgraph cut does not. On the dense OpenIE graph both matter.

A dense-rank-weighted teleport (seed weight = sum of 1/rank of the anchors mentioning
it, a cheap form of HippoRAG 2's dense reset scores) was simulated offline: with the
gold anchor at dense rank 1 it lifts the 5-anchor result from 193 to 348 of 1,000, at
rank 2 to 210, and at rank 3 it drops to 129. Whether it helps therefore depends on the
real dense ranking; it is not implemented and belongs in the tune-half comparison.

### 5.4 Model-free proxy: BM25 first stage + PPR channel (`lexical_proxy.py`)

To see whether a better channel turns into better recall once fused, without the
production models: BM25 (Okapi, k1 = 0.9, b = 0.4, over `title\ntext`) as the first
stage, its top 5 as PPR anchors, the channel's top 5 fused in. Two readings:
candidate-pool coverage (what a reranker could work with; compared with a BM25 pool of
the same size) and weighted RRF without any reranker (graph weight chosen on the tune
half from {0, 0.1, 0.25, 0.5, 0.75, 1}, evaluated on the confirm half). "-novel" =
anchors excluded from the channel (`EXCLUDE_DENSE_ANCHORS`).

BM25 alone, R@2 / R@5: MuSiQue 32.5 / 42.9 (tune), 33.0 / 42.5 (confirm); 2Wiki 56.4 / 67.5
(tune), 56.9 / 67.8 (confirm).

**Candidate-pool coverage** (share of gold passages in the pool, all 1,000 questions;
last column: confirm half, per-question paired sign test against the same-size BM25
top-35 pool):

| MuSiQue (OpenIE graph) | gold share | last hop in pool | confirm: wins / losses vs BM25@35 |
| --- | --- | --- | --- |
| BM25 top 30 | 62.1 | 458 | — |
| BM25 top 35 (control) | 63.1 | 468 | — |
| + production PPR | 62.2 | 460 | 1 / 15 (p = 0.0005), worse |
| + production PPR, -novel | 62.2 | 460 | 1 / 15 (p = 0.0005), worse |
| + `seeds` | 62.8 | 469 | 8 / 15 (p = 0.21) |
| + `seeds`, -novel | 62.9 | 471 | 11 / 15 (p = 0.56) |
| + `specific` + `seeds` | 62.3 | 462 | 2 / 16 (p = 0.001), worse |
| + `specific` + `seeds`, -novel | **65.9** | **527** | **50 / 14 (p < 0.0001)** |
| + `specific` + `ranked` | 64.3 | 499 | 33 / 16 (p = 0.02) |
| + `specific` + `ranked`, -novel | **69.8** | **592** | **96 / 13 (p < 0.0001)** |

| 2Wiki (title-mention graph) | gold share | last hop in pool | confirm: wins / losses vs BM25@35 |
| --- | --- | --- | --- |
| BM25 top 30 | 75.2 | 508 | — |
| BM25 top 35 (control) | 75.6 | 515 | — |
| + production PPR | 76.2 | 528 | 12 / 4 (p = 0.08) |
| + production PPR, -novel | 81.6 | 633 | 71 / 4 (p < 0.0001) |
| + `seeds` | 76.1 | 528 | 8 / 3 (p = 0.23) |
| + `seeds`, -novel | 89.0 | 776 | 159 / 2 (p < 0.0001) |
| + `specific` + `seeds` | 81.2 | 623 | 70 / 2 (p < 0.0001) |
| + `specific` + `seeds`, -novel | **93.6** | **866** | **210 / 2 (p < 0.0001)** |
| + `specific` + `ranked` | 90.8 | 817 | 185 / 2 (p < 0.0001) |
| + `specific` + `ranked`, -novel | **96.2** | **924** | **232 / 1 (p < 0.0001)** |

Without anchor exclusion the channel's top 5 is mostly the anchors themselves, which
BM25 already has (mean pool size 30.2 for `specific` on MuSiQue), so it cannot add
anything; the production channel with anchors excluded is still worse than five more
BM25 passages on MuSiQue.

**Rank fusion without a reranker** (weighted RRF of BM25 top 30 and the channel's top 5;
graph weight chosen on the tune half; confirm half, paired against BM25 alone):

| | chosen graph weight | tune R@5 at weight 1 (equal vote) | confirm R@5: BM25 → fused | wins / losses | sign-test p |
| --- | --- | --- | --- | --- | --- |
| MuSiQue, production PPR | 0.1 | 35.7 | 42.5 → 42.5 | 3 / 3 | 1.0 |
| MuSiQue, production PPR, -novel | 0 | 34.6 | 42.5 → 42.5 | 0 / 0 | 1.0 |
| MuSiQue, `specific` + `seeds`, -novel | 0.1 | 38.4 | 42.5 → 43.2 | 23 / 15 | 0.26 |
| MuSiQue, `specific` + `ranked` | 0.5 | 43.4 | 42.5 → 42.4 | 17 / 19 | 0.87 |
| MuSiQue, `specific` + `ranked`, -novel | 0.25 | 41.9 | 42.5 → 42.8 | 40 / 35 | 0.64 |
| 2Wiki, production PPR | 0 | 61.5 | 67.8 → 67.8 | 0 / 0 | 1.0 |
| 2Wiki, production PPR, -novel | 0.25 | 64.2 | 67.8 → 67.2 | 18 / 17 | 1.0 |
| 2Wiki, `seeds`, -novel | 0.5 | 68.4 | 67.8 → 68.3 | 37 / 24 | 0.12 |
| 2Wiki, `specific` + `seeds`, -novel | 1.0 | 75.4 | **67.8 → 76.8** | **172 / 56** | **< 0.0001** |
| 2Wiki, `specific` + `ranked` | 1.0 | **81.1** (best on tune) | **67.8 → 80.3** | **170 / 14** | **< 0.0001** |
| 2Wiki, `specific` + `ranked`, -novel | 1.0 | 79.4 | 67.8 → 81.2 | 222 / 60 | < 0.0001 |

This is a proxy (BM25 is not the production retriever, and there is no cross-encoder),
but it separates two questions. Only the channel with both new settings and anchor
exclusion adds gold to the pool beyond what five more BM25 passages add. And rank
fusion without a reranker does not turn that into top-5 recall: equal-weight RRF loses
up to 8.3 R@5 on MuSiQue, and the tuned weight is at best a statistically
insignificant gain on the confirm half. Whatever the graph contributes has to be
realised by the cross-encoder and a fusion that does not bury graph-only candidates,
which is what the modes of §3.1 are for, and what §4 tests.

### 5.5 End-to-end: HippoRAG MuSiQue, tune half (500 questions)

Production pipeline (`pipeline_probe`, `k = 25`, query expansion and classifier off,
`--skip-graph-enrichment`), cross-encoder `bge-reranker-v2-m3`, hybrid nomic-embed-text +
SPLADE first stage. "Context" = the fragments handed to the answer model.

| configuration | R@2 | R@5 | R@10 | last hop @5 | hop 0 @5 | both gold in context | last hop in context |
| --- | --- | --- | --- | --- | --- | --- | --- |
| no graph, calibrated | 46.5 | 61.0 | 67.7 | 254 | 418 | 223 | 337 |
| ppr+, cross-encoder only | 46.1 | 60.6 | 68.8 | 234 | 427 | 271 | 375 |
| ppr+, calibrated | 44.3 | 60.4 | 70.1 | 248 | 407 | 269 | 377 |
| no graph, rrf | 45.2 | 60.0 | 68.6 | 248 | 410 | 223 | 338 |
| no graph, cross-encoder only | 46.2 | 59.9 | 66.8 | 227 | 425 | 226 | 338 |
| BFS (prod), rrf | 44.9 | 59.5 | 68.2 | 246 | 409 | 222 | 338 |
| PPR -novel (prod), calibrated | 45.1 | 59.0 | 66.1 | 235 | 415 | 218 | 332 |
| ppr+, signal | 45.7 | 59.0 | 69.0 | 223 | 418 | 242 | 353 |
| PPR -novel (prod), rrf | 42.0 | 58.8 | 67.7 | 240 | 406 | 220 | 336 |
| PPR (prod), rrf | 39.5 | 58.5 | 67.8 | 239 | 405 | 220 | 336 |
| BFS (prod), signal | 45.6 | 58.4 | 68.1 | 221 | 415 | 226 | 340 |
| ppr+, rrf | 35.4 | 58.4 | 71.7 | 242 | 387 | 277 | 383 |
| no graph, signal | 45.6 | 58.3 | 68.0 | 220 | 415 | 225 | 339 |
| PPR (prod), calibrated | 43.9 | 58.3 | 66.3 | 230 | 415 | 219 | 332 |
| PPR -novel (prod), signal | 45.6 | 58.2 | 67.8 | 219 | 415 | 225 | 339 |
| PPR (prod), signal | 45.6 | 58.2 | 67.8 | 219 | 415 | 225 | 339 |
| no graph, no cross-encoder (first stage) | 40.1 | 52.5 | 64.3 | 211 | 362 | 220 | 333 |

`bridge` under "ppr+" was stopped after 177 of the 500 questions for futility and cost:
on those 177 it reached R@5 55.2 and R@2 37.1, against 58.9 / 42.7 for `off:calibrated`
and 57.0 / 41.1 for "ppr+" `calibrated` on the same questions, with about 5 hours of CPU
left (its conditional cross-encoder pairs are ~430 tokens). It is excluded from the
selection; the partial rows are kept.

Candidate pool (all merged candidates, i.e. what the cross-encoder sees):

| channel | gold passages in pool | last hop in pool | graph-only gold passages |
| --- | --- | --- | --- |
| no graph (dense + SPLADE top 30) | 75.2% | 341 | — |
| BFS (production) | 75.3% | 342 | 1 |
| PPR, PPR -novel (production) | 75.2% | 341 | 0 |
| "ppr+" | **80.9%** | **386** | **66** |

**Selection** (pre-registered rule, highest tune R@5): `off:calibrated`, R@5 61.0: the
fusion change *without* the graph. Tune-half paired comparisons (exploratory):

| comparison | R@5 | last hop @5 | both gold in context |
| --- | --- | --- | --- |
| `off:calibrated` vs `off:signal` | +2.6 (CI 1.0 to 4.2, 68 / 35, p = 0.002) | +6.8 (49 / 15) | -0.4 (1 / 3) |
| "ppr+" `calibrated` vs `off:calibrated` | -0.5 (52 / 65, p = 0.27) | -1.2 | **+9.2 (48 / 2, p < 0.0001)** |
| "ppr+" `signal` vs `off:signal` | +0.6 (8 / 0, p = 0.008) | +0.6 | +3.4 (17 / 0) |

Learned fusion (5-fold CV within the tune half, logistic regression): "ppr+" R@5 64.3
(static features) / 64.9 (query-conditioned); no graph 61.9 / 61.8.

### 5.6 End-to-end: HippoRAG MuSiQue, confirm half (500 held-out questions)

| configuration | R@2 | R@5 | R@10 | last hop @5 | hop 0 @5 | both gold in context | last hop in context |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ppr+, learned (online pipeline) | 46.9 | 62.8 | 73.5 | 248 | 425 | 289 | 388 |
| ppr+, learned (offline replay of the signal dump) | 46.7 | 62.7 | 73.5 | 248 | 425 | 289 | 388 |
| ppr+, calibrated | 45.9 | 61.9 | 72.6 | 249 | 415 | 274 | 374 |
| no graph, learned (offline replay of the signal dump) | 47.2 | 60.5 | 67.7 | 221 | 430 | 225 | 334 |
| no graph, calibrated | 47.0 | 60.0 | 68.0 | 222 | 423 | 220 | 326 |
| ppr+, cross-encoder only | 47.4 | 59.6 | 68.3 | 215 | 427 | 268 | 369 |
| no graph, cross-encoder only | 46.9 | 58.9 | 66.8 | 211 | 424 | 222 | 329 |
| ppr+, signal | 47.5 | 58.8 | 68.1 | 208 | 427 | 233 | 339 |
| BFS (prod), signal | 46.9 | 58.2 | 67.3 | 205 | 425 | 222 | 329 |
| PPR (prod), signal | 47.0 | 58.1 | 67.1 | 204 | 425 | 220 | 327 |
| no graph, signal | 47.0 | 58.1 | 67.2 | 204 | 425 | 221 | 328 |
| no graph, no cross-encoder (first stage) | 39.9 | 52.3 | 63.2 | 191 | 373 | 216 | 323 |

"Offline replay" rows rank the candidates of the `signal` dump with a model fitted on the
tune half's dump of the same channel; "online" rows are `pipeline_probe --fusion learned`
with the shipped model.

Pre-registered comparisons (paired per question; bootstrap 95% CI; exact sign test):

| comparison | R@2 | R@5 | last hop @5 | both gold in context |
| --- | --- | --- | --- | --- |
| **H1** selected `off:calibrated` vs production `bfs:signal` | +0.1 (23 / 24) | **+1.75** (CI 0.3 to 3.2, 60 / 36, **p = 0.018**) | +3.4 (36 / 19, p = 0.03) | -0.4 (3 / 5) |
| H1 without the 42 questions shared with dev-150 | +0.2 | +2.0 (CI 0.5 to 3.5, 58 / 33, p = 0.012) | +3.7 (p = 0.024) | -0.2 |
| `off:calibrated` vs cross-encoder-only control | +0.1 | +1.1 (CI -0.5 to 2.7, 58 / 40, p = 0.085) | +2.2 | -0.4 |
| **H2** "ppr+" `calibrated` vs `off:calibrated` | -1.1 (35 / 55, p = 0.045) | +1.9 (CI -0.1 to 4.0, 81 / 65, p = 0.21) | +5.4 (65 / 38, p = 0.010) | **+10.8** (CI 8.0 to 13.6, **56 / 2**, p < 0.0001) |
| "ppr+" `calibrated` vs production `bfs:signal` | -0.9 | +3.7 (CI 1.6 to 5.8, 98 / 61, p = 0.004) | +8.8 (73 / 29) | +10.4 (58 / 6) |
| **H3** learned "ppr+" vs `bfs:signal` | -0.2 (52 / 58) | **+4.5** (CI 2.8 to 6.2, 85 / 31, p < 0.0001) | +8.6 (57 / 14) | +13.4 (71 / 4) |
| H3 learned "ppr+" vs `off:calibrated` | -0.3 | +2.7 (CI 0.9 to 4.6, 73 / 44, p = 0.009) | +5.2 (51 / 25) | +13.8 (73 / 4) |
| H3 learned "ppr+" vs learned without graph | -0.5 | +2.2 (CI 0.8 to 3.6, 49 / 25, p = 0.007) | +5.4 (37 / 10) | +12.8 (68 / 4) |
| H3 learned "ppr+" vs "ppr+" cross-encoder only | -0.7 | +3.1 (CI 1.6 to 4.6, 63 / 26, p = 0.0001) | +6.6 (45 / 12) | +4.2 (25 / 4) |
| H3 learned "ppr+" vs `bfs:signal`, without dev-150 overlap | -0.9 | +4.0 (CI 2.3 to 5.8, 75 / 29, p < 0.0001) | +7.6 | +11.4 |

Reading, with the caveats that belong to it:

- **H1 holds**: replacing the production blend (`0.6 * signal + 0.4 * minmax(ce)`) by the
  calibrated convex combination gains 1.75 R@5 on held-out questions; the effect shrank
  from +2.5 on the tune half, as expected after selection. About two thirds of it is
  simply "stop burying the cross-encoder's tail": the cross-encoder-only control is
  within 1.1 R@5 of it. No graph is involved, so the pre-registered PR criterion for a
  graph + dense fusion ("the graph contributes") is not met by the selected
  configuration.
- **H2 holds for the answer context, not for R@5**: with "ppr+" both gold passages reach
  the answer model for 10.8 points more questions (56 wins, 2 losses), and the last hop
  is in the top 5 more often, while R@2 drops by 1.1 and R@5 moves within noise (tune
  half -0.5, confirm half +1.9). The two halves disagree on the sign of the R@5
  difference, which is what "not significant" looks like.
- **H3 holds on every comparison**, including against the same learned fusion without
  the graph: the graph channel carries signal that fixed weights do not extract and a
  logistic regression over 20 features, fitted on 500 other questions of the same set,
  does. Whether that model transfers to another dataset is tested on 2Wiki below; a
  model fitted on one benchmark is the obvious overfitting risk.

### 5.7 End-to-end: 2Wiki transfer (1,000 questions, all held out)

Nothing was selected or fitted on 2Wiki: the `learned` model is the one fitted on the
MuSiQue tune half, and "ppr+" runs on the title-mention graph with the MuSiQue settings.

| configuration | R@2 | R@5 | R@10 | last hop @5 | hop 0 @5 | both gold in context | last hop in context |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ppr+, learned (online pipeline) | 71.7 | 85.7 | 92.0 | 702 | 1000 | 897 | 930 |
| ppr+, learned (offline replay of the signal dump) | 71.7 | 85.6 | 92.0 | 701 | 1000 | 895 | 928 |
| ppr+, calibrated | 70.5 | 85.3 | 90.0 | 688 | 1000 | 827 | 869 |
| ppr+, cross-encoder only | 66.2 | 74.3 | 80.8 | 487 | 999 | 812 | 863 |
| ppr+, signal | 66.1 | 73.4 | 78.0 | 470 | 1000 | 636 | 673 |
| no graph, learned (online; the ppr+ model with the graph channel off) | 66.9 | 72.7 | 76.3 | 457 | 1000 | 553 | 589 |
| no graph, learned (offline replay of the signal dump) | 66.8 | 72.7 | 76.1 | 456 | 1000 | 551 | 586 |
| no graph, calibrated | 66.4 | 72.5 | 76.2 | 454 | 1000 | 550 | 583 |
| BFS (prod), signal | 65.7 | 71.8 | 75.3 | 439 | 1000 | 552 | 587 |
| no graph, signal | 65.7 | 71.8 | 75.3 | 439 | 1000 | 552 | 587 |
| no graph, no cross-encoder (first stage) | 64.8 | 71.5 | 75.2 | 437 | 997 | 543 | 576 |
| no graph, cross-encoder only | 65.6 | 71.4 | 74.8 | 431 | 999 | 551 | 586 |

| comparison (paired, 1,000 questions) | R@2 | R@5 | last hop @5 | both gold in context |
| --- | --- | --- | --- | --- |
| H1 transfer: `off:calibrated` vs `bfs:signal` | +0.7 (24 / 11, p = 0.041) | +0.7 (CI 0.0 to 1.35, 34 / 20, p = 0.076) | +1.5 (p = 0.049) | -0.2 |
| `off:calibrated` vs cross-encoder-only control | +0.8 (p = 0.026) | +1.1 (46 / 22, p = 0.005) | +2.3 | -0.1 |
| "ppr+" `calibrated` vs `off:calibrated` | +4.1 (123 / 47) | +12.8 (CI 11.4 to 14.1, 333 / 21) | +23.4 | +27.7 (278 / 1) |
| **learned "ppr+" (online) vs `bfs:signal`** | **+6.0** (143 / 25) | **+13.8** (CI 12.5 to 15.1, **338 / 9**, p < 0.0001) | +26.3 | **+34.5** (349 / 4) |
| learned "ppr+" vs learned without graph (online) | +4.8 | +13.0 (324 / 13) | +24.5 | +34.4 |
| learned "ppr+" vs "ppr+" cross-encoder only | +5.5 | +11.4 (283 / 7) | +21.5 | +8.5 |

By question type (R@5, production → learned "ppr+"): compositional 65.0 → 88.1 (413),
inference 72.7 → 83.8 (108), bridge-comparison 54.3 → 67.1 (235), comparison 100 → 100
(244, both entities are named in the question). The gain sits where a bridge is needed.

On MuSiQue confirm the same breakdown by hop count (production / `off:calibrated` /
learned "ppr+"): 2-hop 65.6 / 66.9 / 70.2 (257), 3-hop 55.9 / 58.2 / 60.6 (170), 4-hop
38.0 / 39.7 / 41.8 (73).

Caveat: the title-mention graph favours gold structurally (§5.2: 14.7% of gold passages
isolated vs 60.1% of distractors), because 2Wiki's gold passages are the Wikipedia pages
of entities linked by a Wikidata relation. HippoRAG's graph on 2Wiki has the same
property (the gold pages name each other). The 2Wiki gain is real for this corpus but is
larger than what a graph without that structure would give; MuSiQue (balanced OpenIE
graph) is the conservative estimate.

### 5.8 Against published numbers

Passage R@5 (HippoRAG definition). Ours: MuSiQue on the confirm half (500 held-out
questions; the tune half trained the learned model), 2Wiki on all 1,000.

| System | first stage | MuSiQue R@5 | 2Wiki R@5 |
| --- | --- | --- | --- |
| Contriever | Contriever | 46.6 | 57.5 |
| ColBERTv2 | ColBERTv2 | 49.2 | — |
| HippoRAG | ColBERTv2 | 51.9 | 89.1 |
| NV-Embed-v2 | NV-Embed-v2 (7B) | 69.7 | 76.5 |
| HippoRAG 2 | NV-Embed-v2 + Llama-3.3-70B | 74.7 | 90.4 |
| PropRAG | — | 78.3 | — |
| BridgeRAG (LLM judge) | — | 81.5 | 95.3 |
| Metronix first stage (nomic-embed-text 137M + SPLADE) | | 52.3 | 71.6 |
| Metronix production (`bfs:signal`, + bge-reranker-v2-m3) | | 58.3 | 71.9 |
| Metronix `off:calibrated` | | 60.0 | 72.5 |
| **Metronix learned "ppr+"** | | **62.8** | **85.7** |

In absolute terms Metronix stays below HippoRAG 2 on both sets and below plain
NV-Embed-v2 on MuSiQue: the 137M embedder is the limit, not the fusion. The comparable
quantity is the gain of graph fusion over the same system without it: HippoRAG 2 +5.0
(MuSiQue) and +13.9 (2Wiki) over NV-Embed-v2; learned "ppr+" over learned without graph
+2.2 (MuSiQue confirm) and +13.0 (2Wiki), and over the production pipeline +4.5 and +13.8.
None of these numbers is a new state of the art.

### 5.9 Scaling defects found on the way (not fusion, but they block graph retrieval)

| Defect | Where | Effect on the HippoRAG MuSiQue graph | Status |
| --- | --- | --- | --- |
| PPR subgraph cut at an edge limit in traversal order | `get_ppr_subgraph` | next hop loaded for 67 of 1,000 questions with five anchors (§5.3) | opt-in `SUBGRAPH=specific` |
| PPR teleport uniform over the subgraph's entities | `recall_graph_ppr_async` | with a hub-heavy subgraph the walk drifts away from the seeds (§5.3) | opt-in `TELEPORT=seeds` / `ranked` |
| One unlabelled `MATCH (d)` node scan per document label | `get_doc_labels_by_entities`, called by the BFS channel and by post-rerank graph enrichment | up to 31 s per call; the default BFS channel took ~20 s per question | fixed: one labelled query, identical output, 25-240x faster |
| Graph extraction timeout (300 s) shorter than a capped generation (2,048 tokens; ~400 s for qwen2.5:3b on 2 CPU threads), and a timed-out call sent up to 12 times (urllib3 re-sends the POST 3 times, the extraction loop retries 3 times) | `core/http.py` retry policy, `extract_graph_from_text`, `GRAPH_EXTRACTION_LLM_TIMEOUT` | up to 12 x 300 s per paragraph: the observed 20-60 min. (An earlier version of this row blamed retries queued behind a still-running generation; Ollama 0.34.4 cancels a generation when the client disconnects, so the cost is the re-sent requests.) | harness sets the timeout to 900 s; fixed in #517 (one attempt per timeout, default 600 s) |

### 5.10 The 150-question dev slice (oracle graph) and the qwen2.5:3b graph slice

**Dev slice, oracle graph** (continuity with the earlier session; the oracle topology
leaks gold, §5.2, so none of this selects anything). Same pipeline, 150 questions,
graph enrichment on, cross-encoder cache from the earlier session:

| configuration | R@2 | R@5 | R@10 | last hop @5 | hop 0 @5 | both gold in context | last hop in context |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ppr+, learned | 71.3 | 89.3 | 95.3 | 128 | 140 | 146 | 148 |
| ppr+, calibrated | 67.7 | 88.3 | 95.7 | 120 | 145 | 145 | 147 |
| PPR -novel (prod), calibrated | 68.0 | 88.0 | 95.0 | 119 | 145 | 142 | 144 |
| PPR (prod), rrf | 60.3 | 85.0 | 91.7 | 108 | 147 | 140 | 142 |
| PPR -novel (prod), rrf | 64.0 | 83.3 | 95.3 | 111 | 139 | 146 | 147 |
| PPR (prod), calibrated | 67.7 | 81.7 | 84.7 | 99 | 146 | 120 | 122 |
| PPR (prod), learned | 62.7 | 81.0 | 89.7 | 103 | 140 | 140 | 142 |
| BFS (prod), calibrated | 67.0 | 80.3 | 85.0 | 97 | 144 | 121 | 123 |
| BFS (prod), rrf | 65.7 | 77.3 | 85.3 | 91 | 141 | 121 | 123 |
| no graph, calibrated | 55.0 | 68.7 | 73.7 | 63 | 143 | 93 | 95 |
| ppr+, signal | 55.3 | 67.3 | 77.7 | 62 | 140 | 109 | 111 |
| PPR -novel (prod), signal | 55.3 | 67.3 | 77.7 | 62 | 140 | 109 | 111 |
| no graph, rrf | 55.3 | 67.0 | 76.0 | 62 | 139 | 95 | 97 |
| PPR (prod), signal | 55.0 | 66.7 | 77.0 | 60 | 140 | 105 | 107 |
| BFS (prod), signal | 55.0 | 66.3 | 76.3 | 59 | 140 | 102 | 104 |
| no graph, signal | 54.7 | 65.0 | 74.3 | 55 | 140 | 95 | 97 |

`off:signal` reproduces the earlier session exactly (R@2 54.67, R@5 65.00, both in
context 95). On this graph every graph-aware fusion looks excellent (R@5 up to 89.3), as
the earlier session found; "ppr+" and production `ppr-novel` are identical under
`signal` because the channel settings change nothing on a graph whose subgraphs hold two
passages (§5.3). Production `ppr:rrf` gives R@5 85.00 here vs 84.67 in the earlier
session: 16 questions shift by one rank because PPR ties are broken in an order that
depends on Neo4j element ids, which change when the graph is reloaded (the production
channel is not bit-reproducible across reloads; the new settings share that property).

**qwen2.5:3b graph slice** (`musique-llm`: the first 30 questions of the dev slice, all
2-hop; 535 passages, their own paragraphs plus distractors; graph extracted by Metronix's
own pipeline with qwen2.5:3b on CPU). The graph is sparse: 5.7 entities per passage,
12 passages with none. With the right anchor (`ppr_ceiling.py`) the next-hop passage is
in the channel's subgraph for 21 of 30 questions, and in its top 5 for 21 (one anchor)
or 13 / 14 (five anchors: production `paths` / `specific` + `seeds`). With a few
hundred passages the production subgraph is not cut, so offline the `specific` subgraph
changes little here, unlike on the OpenIE graph (§5.3). End to end, "ppr+" (the `specific`
subgraph plus the `ranked` teleport) still beats production `ppr-novel` under the same
fusion (last row of the paired table below); which of the two
settings carries that on this graph was not ablated.

| configuration | R@2 | R@5 | R@10 | last hop @5 | hop 0 @5 | both gold in context | last hop in context |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ppr+, calibrated | 70.0 | 80.0 | 88.3 | 18 | 30 | 28 | 28 |
| ppr+, learned | 66.7 | 78.3 | 88.3 | 19 | 28 | 29 | 29 |
| BFS (prod), rrf | 63.3 | 75.0 | 80.0 | 15 | 30 | 26 | 26 |
| BFS (prod), calibrated | 66.7 | 73.3 | 80.0 | 14 | 30 | 26 | 26 |
| PPR -novel (prod), rrf | 56.7 | 71.7 | 80.0 | 14 | 29 | 27 | 27 |
| no graph, rrf | 56.7 | 70.0 | 78.3 | 12 | 30 | 24 | 24 |
| PPR -novel (prod), calibrated | 60.0 | 70.0 | 76.7 | 12 | 30 | 26 | 26 |
| PPR (prod), learned | 56.7 | 68.3 | 75.0 | 13 | 28 | 25 | 25 |
| no graph, calibrated | 63.3 | 66.7 | 75.0 | 10 | 30 | 24 | 24 |
| PPR (prod), signal | 56.7 | 65.0 | 75.0 | 10 | 29 | 24 | 24 |
| BFS (prod), signal | 56.7 | 65.0 | 75.0 | 10 | 29 | 24 | 24 |
| no graph, learned | 55.0 | 65.0 | 75.0 | 12 | 27 | 24 | 24 |
| ppr+, signal | 56.7 | 65.0 | 75.0 | 10 | 29 | 25 | 25 |
| PPR (prod), rrf | 46.7 | 65.0 | 75.0 | 10 | 29 | 25 | 25 |
| PPR (prod), calibrated | 58.3 | 65.0 | 71.7 | 9 | 30 | 24 | 24 |
| PPR -novel (prod), signal | 56.7 | 65.0 | 75.0 | 10 | 29 | 24 | 24 |
| no graph, signal | 56.7 | 65.0 | 75.0 | 10 | 29 | 24 | 24 |

Paired comparisons, 30 questions (A is the configuration after "vs"):

| B vs A | R@2 | R@5 (CI) | wins / losses (R@5) | last hop @5 | both in context |
| --- | --- | --- | --- | --- | --- |
| ppr+ `learned` vs `bfs:signal` | +10.0 | +13.3 (3.3 to 23.3) | 10 / 2, p = 0.039 | +30.0 (p = 0.012) | +16.7 (5 / 0, p = 0.063) |
| ppr+ `calibrated` vs `bfs:signal` | +13.3 | +15.0 (3.3 to 26.7) | 10 / 2, p = 0.039 | +26.7 (p = 0.039) | +13.3 (5 / 1, p = 0.22) |
| ppr+ `learned` vs no-graph `learned` | +11.7 | +13.3 (5.0 to 23.3) | 9 / 1, p = 0.022 | +23.3 (p = 0.039) | +16.7 (5 / 0, p = 0.063) |
| ppr+ `calibrated` vs production `ppr-novel:calibrated` | +10.0 | +10.0 (3.3 to 18.3) | 6 / 0, p = 0.031 | +20.0 (p = 0.031) | +6.7 (3 / 1, p = 0.63) |

What this slice does and does not show:

- It reproduces #497's diagnosis on Metronix's own graph: under `signal` every graph
  mode gives the same R@5 (65.0) as no graph, and the last hop reaches the top 5 in
  10 of 30 (the earlier REPORT: 9 of 30). The candidates are there: from the same "ppr+"
  pool, `signal` puts the last hop in the top 5 for 10 questions and `learned` for 19.
- The direction agrees with the two large sets: the graph-aware fusions ("ppr+" with
  `calibrated` or `learned`) are the only configurations above 75 R@5, and graph helps
  `learned` (+13.3 R@5 over the same model without graph). With production channels,
  `calibrated` and `rrf` gain less (65.0 to 75.0) and `learned` with production PPR
  (68.3) barely moves.
- Five of the 30 questions are in the MuSiQue tune half the `learned` model was fitted
  on. Without them (25 questions) ppr+ `learned` vs `bfs:signal` is +16.0 R@5 (CI 4 to
  28, 10 / 2), so the result is not carried by them.
- It is 30 questions: one question moves R@5 by 1.7 to 3.3 points, the confidence
  intervals are 20 points wide, and no Bonferroni-style correction was applied across
  the rows above. All 30 were part of the 150-question slice the earlier session used to
  design the fusion modes. This slice is a consistency check on a small, sparse graph,
  not evidence of the size of the gain; the effect sizes to quote are the MuSiQue
  confirm half and 2Wiki (§5.6, §5.7).
- `learned` loses hop 0 in 2 of 30 questions (the dev slice: 140 vs 145 for
  `calibrated`); the model trades some first-hop precision for the second hop.

### 5.11 Which half of "ppr+" carries the gain (ablation)

"ppr+" changes two things at once: the subgraph (`SUBGRAPH=specific`) and the teleport
(`TELEPORT=ranked`). Each was switched on alone, on the qwen2.5:3b slice of §5.10
(30 questions, `ppr-novel`, same cross-encoder cache; a rerun of full "ppr+" after a
machine restart reproduced every rank):

| channel settings | R@5 `calibrated` | last hop @5 | R@5 `learned` | last hop @5 |
| --- | --- | --- | --- | --- |
| production (`paths`, `subgraph` teleport) | 70.0 | 12 | — | — |
| `specific` only | 70.0 | 12 | 68.3 | 14 |
| `seeds` teleport only | 73.3 | 14 | 76.7 | 18 |
| `ranked` teleport only | 78.3 | 17 | 76.7 | 18 |
| `specific` + `seeds` | 75.0 | 15 | 76.7 | 18 |
| `specific` + `ranked` ("ppr+") | 80.0 | 18 | 78.3 | 19 |

Paired, `calibrated`: `ranked` alone vs production +8.3 R@5 (5 wins / 0 losses, p = 0.063),
`seeds` alone +3.3 (2 / 0), `specific` alone changes no question's top 5; adding
`specific` to `ranked` +1.7 (2 / 1); `ranked` vs `seeds` +5.0 (3 / 0, p = 0.25).

On this graph the teleport carries the gain and the subgraph adds almost nothing, which
matches §5.10: with 535 passages the production subgraph is not cut. On the OpenIE graph
(11,656 passages) the channel probe of §5.3 shows the opposite need, with the two
settings interacting: with five anchors the next hop reaches the top 5 for 14 of 1,000
questions in production, 42 with the `seeds` teleport alone, 21 with the `specific`
subgraph alone and 192 with both, because the production subgraph holds the next hop
for only 67 questions (737 with `specific`) and a uniform teleport over the larger
subgraph drifts away from the seeds. So which half matters depends on the graph size;
both stay on in the recommended configuration. The production subgraph now logs
`graph_ppr.subgraph_truncated` when it is cut. With the gold hop-0 passage as anchor
(plus four of the question's distractors for five anchors), it was cut:
- on the qwen2.5:3b graph in 0 of 30 queries with one or five anchors;
- on the OpenIE graph in 74 of the first 100 confirm-half queries with one anchor and in
  100 of 100 with five.

How often a workspace logs this event tells whether `specific` changes its results. The end-to-end ablation was not repeated
on the MuSiQue confirm half; the 30-question differences between the teleport variants
(1 to 3 questions) are within noise.

## 6. Negative and null results

- **Equal-vote `rrf` with a noisy graph channel**: R@2 falls from 45.2 to 35.4 on the
  MuSiQue tune half with "ppr+" (from 45.6 to 39.5 with production PPR), because a graph
  candidate at rank 1 gets the same vote as the cross-encoder's rank 1.
- **`bridge`** (chain-conditioned cross-encoder, the zero-shot analogue of BridgeRAG) was
  worse than plain `calibrated` on the 177 questions it finished (R@5 55.2 vs 57.0) and
  costs ~40 s per question on CPU; stopped for futility (§5.5).
- **`calibrated` with "ppr+" on MuSiQue**: the two halves disagree on the sign of the R@5
  difference to no-graph `calibrated` (-0.5, +1.9); only the answer-context gain
  (+9 to +11 points) is stable. Fixed weights do not decide when to trust the graph.
- **Query-conditioned features** (MoR-style confidence signals) add +0.6 R@5 over static
  features in cross-validation; the shipped model uses them, but they are not the source
  of the gain.
- **Production channels**: BFS and PPR as shipped change no metric on either dataset
  (§5.5, §5.7); a larger `paths` budget loads more passages but does not rank them
  (next hop in the top 5: 110 vs 112).
- **No LLM-free lexical proxy result transfers to MuSiQue**: rank fusion of BM25 and the
  graph without a reranker is flat there (§5.4), although it gains +12.5 R@5 on 2Wiki.

## 7. Limitations

- **Two benchmarks, one domain.** Both are Wikipedia multi-hop QA. The learned model was
  fitted on 500 MuSiQue questions and transfers to 2Wiki, but a Metronix workspace
  (tickets, docs, chats) is a different distribution; the model is shipped as an opt-in
  starting point, not a default.
- **2Wiki's graph is structurally favourable** (§5.2, §5.7), so its +13.8 is an
  optimistic figure; the MuSiQue OpenIE graph (balanced) gives the conservative one.
- **The OpenIE graph was extracted by Llama-3.3-70B** (released by HippoRAG); Metronix's
  own extractor (qwen2.5:3b on CPU) produces a much sparser graph (§5.10, and the
  REPORT: PPR last hop 9/30 vs 29/30 on the oracle graph).
- **Passage recall, not answer accuracy.** No reader/EM/F1 was run.
- **Deviations from the protocol**: two production-channel `bridge` runs skipped and the
  "ppr+" `bridge` run stopped after 177 questions (both recorded in this note before any
  confirm-half result was read); H2/H3 were added after the tune half and before the
  confirm half.
- **Harness stubs**: LLM calls (resolver, answer, team-workflow router) are stubbed and
  post-rerank graph enrichment is skipped on the HippoRAG sets; neither affects the
  ranking (checked identical on samples).
- CPU-only (4 cores). Latencies were measured on a shared machine; the "ppr+" channel is
  faster than the production PPR channel (§5.3), `learned` adds no model call.

## 8. Reproduce

```bash
git clone --depth 1 https://github.com/OSU-NLP-Group/HippoRAG <dir>
# 1. Load (needs nomic-embed-text in Ollama and the SPLADE model; ~2 h on 4 CPU cores):
python -m benchmarks.musique.scripts.hipporag_set --hipporag-dir <dir> \
  --workspace musique-hipporag --label-prefix mhr --graph openie \
  --manifest <out>/manifest_hipporag.jsonl --reset
python -m benchmarks.musique.scripts.hipporag_set --hipporag-dir <dir> \
  --dataset 2wikimultihopqa --workspace wiki2-hipporag --label-prefix w2h --graph titles \
  --manifest <out>/manifest_2wiki.jsonl --reset
#    (graph only, no models: add --skip-qdrant; then ppr_ceiling.py / lexical_proxy.py)
# 2. Split MuSiQue by index parity into <out>/manifest_hipporag_{tune,confirm}.jsonl.
# 3. One configuration = one pipeline_probe run (bge-reranker-v2-m3 on first use), e.g.
#    production and the learned "ppr+" configuration on the confirm half:
python -m benchmarks.musique.scripts.pipeline_probe --workspace musique-hipporag \
  --manifest <out>/manifest_hipporag_confirm.jsonl --limit 500 --graph bfs --fusion signal \
  --trace --skip-graph-enrichment --rerank-cache <out>/ce.jsonl --output <runs>/prod.json
python -m benchmarks.musique.scripts.pipeline_probe --workspace musique-hipporag \
  --manifest <out>/manifest_hipporag_confirm.jsonl --limit 500 --graph ppr-novel \
  --fusion learned --env METRONIX_RETRIEVAL_GRAPH_PPR_SUBGRAPH=specific \
  --env METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT=ranked \
  --trace --skip-graph-enrichment --rerank-cache <out>/ce.jsonl --output <runs>/learned.json
python -m benchmarks.musique.scripts.compare_runs <runs>/prod.json <runs>/learned.json
python -m benchmarks.musique.scripts.pool_coverage <runs>/prod.json <runs>/learned.json
# 4. Refit the learned model from a tune-half signal dump of the "ppr+" channel:
python -m benchmarks.musique.scripts.fusion_learned <runs>/tune_pprplus_signal.json \
  --features query --export src/metronix/retrieval/fusion_models/default.json
```

The dev and qwen2.5:3b slices (§5.10) are built as in the handoff note (`convert.py`,
`--graph llm` for `musique-llm`; set `GRAPH_EXTRACTION_LLM_TIMEOUT=900` or more on CPU,
§5.9) and run with the same `pipeline_probe` commands without `--skip-graph-enrichment`.

Per-question results of every run in §5.5-§5.7, §5.10 and §5.11 (ranks of the gold passages,
no candidate dumps) are in `benchmarks/musique/results/2026-09-27/`.
