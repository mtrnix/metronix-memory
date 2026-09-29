# Multi-hop retrieval in Metronix: evidence from MuSiQue

Status: **2026-09-24.** Oracle-graph channel results on 150 questions; oracle vs
LLM-extracted graph and end-to-end results on a 30-question subset.

## Summary

Metronix's published benchmarks (LoCoMo, LongMemEval, MemoryAgentBench) conclude that
"relevant evidence is usually found". It is not established that those suites exercise
bridge multi-hop retrieval (§5.5 of the #497 notes found LongMemEval's "multi-session"
questions to be independent facts, not bridges). On MuSiQue-Ans 2-hop questions, where
the second paragraph is reachable only through an entity named in the first, and which
were filtered against single-hop shortcuts, the picture is different:

1. **Hybrid dense + SPLADE retrieval misses the bridge paragraph** from its top 30 in
   53 of 150 questions (35%), while finding the first-hop paragraph at median rank 1.
2. **The default BFS graph channel could not traverse at all** before the #508 fix:
   0 of 150 last-hop paragraphs reached via expansion; 145 of 150 after it.
3. With production seeding (`extract_title_entities`), **BFS is seed-bound**: 90 of 150
   queries produce no usable seed, so the channel returns the last-hop paragraph for
   only 60 of 150.
4. The existing, **opt-in PPR channel** (dense-anchored personalized PageRank) returns
   the last-hop paragraph for **135 of 150**, and dense top-30 ∪ PPR covers it for
   **144 of 150** (dense ∪ BFS: 123; dense alone: 97).
5. PPR spends most of its 5 slots re-returning dense's own anchor documents. Excluding
   the anchors (new opt-in flag) raises dense top-30 ∪ PPR to **149 of 150**
   (prototype measurement).
6. A HippoRAG-2-style teleport (mass on dense anchor documents instead of all entities)
   **did not help** here: 75 of 150 vs 133 for the current uniform teleport.

Items 1-6 use an **oracle graph** built from MuSiQue's gold decompositions, an upper
bound on what the graph channels can contribute. Two results on a 30-question subset
qualify them:

7. **With a graph extracted by Metronix's own pipeline (`qwen2.5:3b`) most of the gain
   disappears.** On the same 535-document corpus PPR returns the last-hop paragraph for
   29 of 30 questions on the oracle graph and **9 of 30** on the LLM graph; dense top-30
   ∪ PPR goes from 30/30 to 25/30 (dense alone: 24/30). The bottleneck on real graphs
   is extraction quality, not the traversal.
8. **Even on the oracle graph, graph-found candidates rarely reach the answer model.**
   PPR adds the missing last-hop paragraph to the candidate pool for 6 of 30 questions,
   but the fragments handed to the LLM contain both gold paragraphs for 25 of 30 with
   PPR versus 24 of 30 without any graph channel: 5 of the 6 are dropped between the
   pool and the context (merge, signal scoring, rerank, top-k). This is where #497's
   score-fusion question applies; the mechanism has not been traced here.

## Setup

**Data.** First 150 answerable 2-hop questions of MuSiQue-Ans dev
(`dgslibisey/MuSiQue` @ `c8f4f8c`), all 20 paragraphs per question (2 supporting,
18 distractors). MuSiQue reuses Wikipedia paragraphs across questions; documents are
deduplicated by content hash: 2999 occurrences → 2328 documents (250 supporting).

**Graphs.**

| Graph | How it is built | Used for |
| --- | --- | --- |
| Oracle | Paragraph titles as entities (MENTIONS); each decomposition step `subject -[relation]-> answer`, both mentioned by the step's supporting paragraph; `answer_aliases` as ALIAS | Upper bound; isolates retrieval logic from extraction quality |
| LLM | Production `write_doc_graph` with `qwen2.5:3b` over "title + paragraph" | Realistic graph; first 30 questions (535 documents) |

**Stack.** Neo4j 5.26 Community, Qdrant 1.18.0 (versions from `docker-compose.yml`),
Ollama 0.34.4 with `nomic-embed-text` (768-d) for dense vectors, local SPLADE
`naver/splade-cocondenser-ensembledistil` for sparse vectors, production
`add_document` ingestion. Run on a 4-core CPU container.

**Channels measured.** `recall_dense` (hybrid dense + sparse RRF, top 30);
`recall_graph` (BFS, default, top 5); `recall_graph_ppr_async` (opt-in PPR anchored on
the top-5 dense documents, top 5). Seeds: `extract_title_entities(question)`
(production) unless stated as *oracle seeds* (the gold step-0 subject).

**Metrics.** Whether the hop-0 and last-hop gold paragraphs are among a channel's
returned documents, and among dense top-30 ∪ graph channel (the candidate pool fusion
can draw on). End-to-end: whether they reach the fragments handed to the answer model
after merge, signal scoring and cross-encoder rerank.

## Results (oracle graph, 150 questions)

### Dense retrieval alone

| | top-5 | top-10 | top-30 |
| --- | --- | --- | --- |
| hop-0 paragraph | 143 | 147 | 149 |
| last-hop paragraph | 62 | 74 | 97 |
| both | 58 | 73 | 97 |

Typical miss: *"Where is Ulrich Walter's employer headquartered?"* — the Ulrich Walter
paragraph is rank 2; the German Aerospace Center → Cologne paragraph shares no terms
with the question and is absent from the top 30.

### Graph channels (production seeds)

| | BFS (default) | PPR (opt-in) |
| --- | --- | --- |
| last-hop paragraph in channel top-5 | 60 | **135** |
| both paragraphs in channel top-5 | 60 | 132 |
| empty result | 90 | 0 |
| dense@30 ∪ channel: last hop | 123 | **144** |
| last hop found only via the graph channel | 26 | 47 |
| mean latency per query (contended CPU) | 46 ms | 86 ms |

With oracle seeds BFS reaches the last hop in 146 of 150 — its weakness is seeding, not
traversal. PPR sidesteps seeding by anchoring on dense results.

### PPR variants (prototype script `ppr_proto.py`, branch `wip/ppr-multihop`)

| Teleport | channel top-5: last hop | dense@30 ∪ channel: last hop |
| --- | --- | --- |
| uniform over subgraph entities (current) | 133 | 143 |
| dense anchor documents, weighted by dense score | 75 | 105 |
| 70% anchor documents + 30% query entities | 91 | 117 |
| any of the above, dense anchors excluded from output | 85 | **149** |

The prototype ranks labels directly; the production channel fetches points for the
ranked labels, which is why its uniform-teleport figure (135) differs slightly from
the prototype's (133).

Teleporting onto the anchor documents concentrates probability mass on the documents
dense already returned, so they fill the top 5. The gain comes from **not spending the
graph channel's slots on dense's own documents**, not from changing the walk. This is
the motivation for `METRONIX_RETRIEVAL_GRAPH_PPR_EXCLUDE_DENSE_ANCHORS`.

The 15 remaining PPR misses are ranking losses around hub entities shared by many
questions (e.g. *Nelson River*, *Vila Franca de Xira*), where the walk's mass spreads
over many documents.

## Results: oracle vs LLM-extracted graph (30 questions, same corpus)

First 30 questions of the slice; their 535 distinct paragraphs are loaded twice, once
with the oracle graph (workspace `musique-o30`) and once with the production
`write_doc_graph` extractor on `qwen2.5:3b` (`musique-llm`). Same documents, same
dense retrieval (dense top-30 finds the last hop for 24/30 in both), so the graph is the
only variable. The smaller corpus makes dense stronger than in the 150-question runs.

The extractor produced 5.7 entities and 3.3 relationships per paragraph on average;
11 of 535 paragraphs yielded none (repetition loops truncated by the output cap). It
misses bridge entities: the *Philae (spacecraft)* paragraph yields *Cologne* but not
*German Aerospace Center*, which is exactly the link the Ulrich Walter question needs.

### Graph channels (production seeds)

| | oracle graph | LLM graph |
| --- | --- | --- |
| BFS: last hop in channel top-5 | 16 | 10 |
| BFS: empty result | 14 | 15 |
| PPR: last hop in channel top-5 | **29** | **9** |
| dense@30 ∪ BFS: last hop | 28 | 27 |
| dense@30 ∪ PPR: last hop | 30 | 25 |
| dense@30 ∪ PPR, anchors excluded: last hop | 30 | 27 |

### End-to-end: does the evidence reach the answer model?

`pipeline_probe.py` runs the production `hybrid_search_and_answer` (LLM calls stubbed,
query expansion and classifier off, `k=25`). "Context" = fragments handed to the answer
model; with 535 short paragraphs all 25 fit the token budget.

| graph mode | oracle: both gold in context | LLM: both gold in context | both in post-rerank top-5 / top-10 (either graph) |
| --- | --- | --- | --- |
| off (no graph channel) | 24 | 24 | 10 / 15 |
| bfs (default) | 24 | 24 | 10 / 15 |
| ppr | 25 | 24 | 10 / 15 |
| ppr, anchors excluded | 25 | 24 | 10 / 15 |

On the oracle graph PPR brings the last-hop paragraph into the candidate pool for 6
questions where dense misses it, yet the context gains one question. On the LLM graph
no graph mode changes the context at all. The post-rerank top-5 and top-10 are
identical across modes: the cross-encoder and fusion rank graph-only candidates below
dense ones. Whether that is the reranker judging the bridge paragraph irrelevant to the
question (it shares no terms with it, by construction) or the fusion scores is the
open #497 question.

On the 150-question oracle run (2328 documents) the same pipeline gives, for the first
30 questions: both gold in context for 17 (off), 18 (bfs), 20 (ppr), 21 (ppr, anchors
excluded) — a larger effect in the harder, larger corpus, still well below the
candidate-pool gains.

## Defects found along the way

| Defect | Effect | Status |
| --- | --- | --- |
| `get_graph_relationships` returned bare `RETURN r` (#508) | endpoint names read as `""`; BFS never expanded (0/150) | fixed, branch `fix/508-graph-relationship-projection` |
| Graph channel cuts BFS labels by Qdrant scroll order (UUID) with constant score 1.0 | 5 of the 15 questions where the cut applies lose BFS-found gold | documented, `findings/2026-09-24-graph-channel-unranked-truncation.md` |
| Extraction LLM call had no output cap | `qwen2.5:3b` looped in JSON mode, holding the worker ~20 min per paragraph plus retries | fixed, branch `fix/graph-extraction-output-cap` (`GRAPH_EXTRACTION_MAX_TOKENS`) |
| Harness: per-question paragraph copies | BFS reached another question's copy of the gold text, scored as a miss (23 of 37 misses) | fixed in `convert.py` (content-hash labels) |

## Limitations

- **Oracle graph** for the 150-question numbers: an upper bound. The LLM-graph
  comparison covers 30 questions and one extractor (`qwen2.5:3b` on CPU).
- **150 questions, 2-hop only, one run.** No 3/4-hop, no variance estimate.
- **Candidate-pool metrics**, not answer accuracy (EM/F1).
- **No external baseline.** Numbers are not yet comparable to published MuSiQue results
  (e.g. HippoRAG 2), which use the full dev set and Recall@2/@5 over passages.
- The PPR anchor-exclusion result is a prototype measurement on the oracle graph and
  may not transfer.
- CPU-only run; latency numbers were measured under contention.

## Reproduce

```bash
python -m benchmarks.musique.scripts.dataset --limit 150
python -m benchmarks.musique.scripts.convert --workspace musique-dev --reset
python -m benchmarks.musique.scripts.probe --limit 150 --seeds title --recall --dense --ppr
python -m benchmarks.musique.scripts.probe --limit 150 --seeds title --recall --dense --ppr \
    --ppr-exclude-anchors
python -m benchmarks.musique.scripts.pipeline_probe --graph ppr --limit 30
# LLM graph (slow on CPU):
python -m benchmarks.musique.scripts.convert --graph llm --workspace musique-llm \
    --label-prefix musique-llm --limit 30 --manifest <path>/manifest_llm30.jsonl --reset
```

## Next steps

1. Trace why graph-found candidates are dropped between the pool and the context
   (#497): per-candidate signal score, rerank score and final rank.
2. Scale to the full MuSiQue dev set (2/3/4-hop) and 2WikiMultiHopQA on a GPU; report
   passage Recall@2/@5 and answer EM/F1 next to published baselines.
3. Compare extractors (3B, 7B, an API model): the oracle-to-LLM gap (PPR 29 → 9 of 30)
   is the largest effect measured here.
4. Decide #156 (PPR take/park) and #497 (score fusion) with this evidence; the
   unranked-truncation observation belongs to #497.
