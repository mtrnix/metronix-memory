# Graph + dense fusion for multi-hop retrieval (#497): research note

Date: 2026-09-26. Continues `2026-09-26-fusion-handoff.md` (same day, earlier session).
Status: **the end-to-end fusion comparison on a non-oracle graph has not been run.**
The container this note was written in could not download the embedding, reranker and
extraction models (its network policy denies `huggingface.co` and `registry.ollama.ai`),
so every number below comes either from the earlier session's runs on the oracle graph
or from measurements that need no model: graph topology, and the PPR graph channel with
known anchors. What was found there changes what the fusion comparison should test, and
the protocol for it is fixed in §4 before any of it is run.

## Summary

1. **The oracle graph cannot select a fusion method** (earlier session, repeated here
   for completeness): in the MuSiQue decomposition graph 92% of distractors are isolated
   and no supporting paragraph is, so "the graph returned it" nearly means "it is gold".
   A cross-validated logistic regression reaches R@5 92.7 on it. Every oracle-graph
   fusion gain (e.g. `ppr`+`rrf` R@5 66.7 → 84.7) is an upper bound of unknown slack.
2. **The HippoRAG 2 MuSiQue graph does not leak.** On the Llama-3.3-70B OpenIE triples
   that HippoRAG 2 released (11,656 passages, 86,919 entities), supporting and distractor
   passages have the same entity counts (12.5 vs 11.9) and neighbourhoods (301 vs 341
   neighbouring passages; 0.3% vs 1.7% isolated). It is a fair test bed, and its
   published numbers give an external reference.
3. **On that graph the production PPR channel almost never reaches the next hop, before
   any fusion happens.** With the gold hop-0 passage and four of the question's
   distractors as anchors (standing in for the dense top 5), the hop-1 passage is in the
   channel's top 5 for **14 of 1,000** questions. The oracle graph gives 150 of 150 on the
   same probe, which is why earlier work never saw this. Two design choices cause it:
   the subgraph is cut at an edge limit in traversal order, so around hub entities
   (one entity is mentioned by 1,294 passages) the next hop is not even loaded (67 of
   1,000), and the teleport is uniform over every entity in the subgraph rather than on
   the seeds.
4. **Two opt-in channel settings fix most of it** (defaults unchanged): teleport on the
   seed entities (`METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT=seeds`, as HippoRAG does) and
   a subgraph grown from the least-mentioned seeds first
   (`METRONIX_RETRIEVAL_GRAPH_PPR_SUBGRAPH=specific`). Together: next hop in the top 5
   for **192 of 1,000** (13.7x), at lower latency (90 ms vs 147 ms median). With the gold
   anchor alone: 112 → 399 of 1,000, where PPR over the entire graph gives 407.
5. **The fusion modes** (`rrf`, `calibrated`, `bridge`, from the handoff) are implemented
   and unit-tested but **not yet evaluated on any non-oracle graph**. Without item 4 they
   would be fusing a channel that returns the bridge passage for about 1% of questions,
   so they must be compared on top of both channel settings.

No claim of a fusion improvement is made here.

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

Weights were fixed before any measurement and are not tuned in this note.

### 3.2 PPR channel settings (new in this session)

| Setting | Values | Effect |
| --- | --- | --- |
| `METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT` | `subgraph` (default), `seeds` | teleport uniform over the subgraph's entities, or over the seed entities only |
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

### 5.5 End-to-end fusion, HippoRAG MuSiQue-1000 and 2Wiki-1000

Not run: the models could not be downloaded in this container (see Status). Commands
are in §8; the protocol is §4.

## 6. Negative and null results so far

- On the oracle graph, query-conditioned weights (MoR-style features in
  `fusion_learned.py`) added nothing over static ones (handoff §2.2).
- Chain-conditioned cross-encoder scoring helps on average but is noisy: in a 20-question
  pilot with the gold anchor, the gold last hop was ranked first 11 times (7 without
  conditioning) and worse in 4 questions (handoff §2.3).
- A larger `paths` budget does not rescue the production channel: 2,000 nodes load the
  next hop for 645 of 1,000 questions (500 nodes: 415) but its top-5 count stays at 110
  with the uniform teleport (gold anchor).
- On the oracle graph, the channel settings of §3.2 change nothing (150 of 150 either
  way), so earlier oracle results are not affected by them.

## 7. Limitations

- No end-to-end number on a non-oracle graph yet; everything in §5.3 is channel-only,
  with gold anchors and distractors as stand-ins for dense anchors.
- The `specific` budget was chosen on all 1,000 questions of the channel probe (§3.2).
- The title-mention graph for 2Wiki is a crude, non-LLM graph with a structural bias
  toward gold (§5.2).
- MuSiQue's 150-question dev slice and qwen2.5:3b graph (30 questions) from the task
  plan are not re-run here: loading and extraction need the same models.
- CPU-only; latencies are for 4 cores with nothing else running.

## 8. Reproduce

```bash
git clone --depth 1 https://github.com/OSU-NLP-Group/HippoRAG <dir>
# graph only (no models needed):
python -m benchmarks.musique.scripts.hipporag_set --hipporag-dir <dir> \
  --workspace musique-hipporag --label-prefix mhr --graph openie \
  --manifest <out>/manifest_hipporag.jsonl --skip-qdrant --reset
python -m benchmarks.musique.scripts.ppr_ceiling --workspace musique-hipporag \
  --manifest <out>/manifest_hipporag.jsonl --extra-anchors 4 --subgraph specific --teleport seeds
python -m benchmarks.musique.scripts.hipporag_set --hipporag-dir <dir> \
  --dataset 2wikimultihopqa --workspace wiki2-hipporag --label-prefix w2h --graph titles \
  --manifest <out>/manifest_2wiki.jsonl --skip-qdrant --reset
# full load (needs nomic-embed-text in Ollama and the SPLADE model): drop --skip-qdrant.
# end-to-end matrix (needs bge-reranker-v2-m3), e.g. the "ppr+" configuration:
RUNS_DIR=<runs> benchmarks/musique/scripts/run_matrix.sh musique-hipporag \
  <out>/manifest_hipporag.jsonl 1000 mhr "off:signal ppr:signal ppr:rrf ppr:calibrated ppr:bridge" \
  --env METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT=seeds \
  --env METRONIX_RETRIEVAL_GRAPH_PPR_SUBGRAPH=specific \
  --env METRONIX_RETRIEVAL_GRAPH_PPR_EXCLUDE_DENSE_ANCHORS=true
```
