# Graph + dense score fusion for multi-hop retrieval (#497): handoff

Date: 2026-09-26. Status: **work in progress, handed off mid-run.** Opt-in fusion modes are
implemented and unit-tested. A mechanism trace and the first real runs on the 150-question
oracle workspace are done. The non-oracle evaluations (qwen2.5:3b graph and the HippoRAG
MuSiQue-1000 set) were still loading when this note was written, so there are **no
non-oracle results yet**, and no claim about a fusion improvement can be made yet.

## 1. What was done

### Code (default behaviour unchanged)

| Change | Where |
| --- | --- |
| Fusion modes `signal` (default, production formula), `rrf`, `calibrated`, `bridge` behind `METRONIX_RETRIEVAL_FUSION_MODE` | `src/metronix/retrieval/fusion.py` (pure functions), wired in `search.py` (`_fused_scores`, `_bridge_scores`) |
| Settings: `METRONIX_RETRIEVAL_FUSION_MODE`, `_RRF_K` (60), `_WEIGHTS` (`"rerank=1,dense=1,graph=1"`, empty means the mode default), `_BRIDGE_ANCHORS` (3), `_BRIDGE_SCOPE` (`graph` or `connected`) | `src/metronix/core/config.py` |
| `get_entity_names_by_doc_label`: document to entity names in one query (used by `bridge`) | `src/metronix/storage/graph_ops.py` |
| `score_pairs`: cross-encoder scores for arbitrary pairs | `src/metronix/retrieval/reranker.py` |
| Tests | `tests/unit/retrieval/test_fusion.py`, `test_search_fusion.py`, `tests/unit/benchmarks/musique/*` (113 tests, all passing) |

In every non-default mode the **rerank pool is chosen by channel RRF** instead of by signal
score, so a graph-only candidate is not cut before rerank. The pool is the same for all
three modes, which isolates the post-rerank fusion. The mode defaults
(`fusion.DEFAULT_WEIGHTS`) were fixed **before any measurement**:

- **`rrf`**: one vote each for the cross-encoder, dense, graph and metadata rankings; k = 60.
- **`calibrated`** (Bruch et al. 2023, TM2C2): the raw cross-encoder probability with
  weight 0.5, plus dense and graph scores divided by their per-query max, 0.25 each.
- **`bridge`**: `calibrated` where each graph candidate also gets the chain score
  `P(anchor | q) * P(candidate | q + anchor text)`. The anchor is the best of the top-3
  cross-encoder passages that shares an entity with the candidate. It is the
  PathRetriever / Beam Retrieval path score, used zero-shot with the existing
  bge-reranker-v2-m3.

### Harness

| Tool | Purpose |
| --- | --- |
| `pipeline_probe.py` | New options: `--fusion`, `--offset`, `--env NAME=VALUE`, `--rerank-cache` (JSONL cross-encoder cache; the model is deterministic, so cached runs are identical to uncached ones), `--trace` (per-gold rank at each stage, plus a full candidate dump with channel scores and CE score). Adds passage recall@2/@5/@10 (HippoRAG definition) and hop-0 hits. |
| `fusion_replay.py` | Re-ranks the dumped candidates offline with the same `fusion.py` functions, for sensitivity analysis. Checked against a real run: `ppr`+`rrf` replay equals the pipeline run exactly. |
| `fusion_learned.py` | Cross-validated logistic-regression fusion (5 folds, split by question), as a headroom check. Has static and query-conditioned (MoR-style) feature sets. |
| `compare_runs.py` | Paired comparison of two runs: bootstrap 95% CI, exact sign test, `--subset`, `--exclude`, `--hops`. |
| `hipporag_set.py` | Loads the HippoRAG / HippoRAG 2 MuSiQue set: 1,000 questions and 11,656 passages, with the **released Llama-3.3-70B OpenIE triples** as the graph. `--graph oracle` builds the decomposition graph instead. |
| `run_matrix.sh` | Runs graph:fusion configurations sequentially, resumable. |

### Data and results committed

- `results/2026-09-26/`: real pipeline runs on `musique-dev` (150 q, oracle graph), all with
  `--trace`; `dev_off_signal.json` has per-stage ranks but no candidate dump, so it cannot be
  replayed. `ce_cache.jsonl` holds
  4,669 cross-encoder scores; keys are `sha1(query \0 passage[:512])`, so it can be reused
  with `--rerank-cache`.
- `data/manifest_llm30.jsonl`: manifest for the `musique-llm` workspace (label prefix
  `musique-llm`, first 30 questions).

## 2. Findings

### 2.1 Why graph-found candidates never reach the context

Trace on `musique-dev`: oracle graph, PPR channel, production `signal` fusion, 150 questions,
k = 25. Both gold paragraphs in context: 105/150, versus 95 with the graph channel removed.
The first 30 questions reproduce the 2026-09-24 report exactly: 17 (off), 18 (bfs), 20 (ppr),
21 (ppr-novel).

Last-hop gold paragraph, by stage:

| Found by | Reached rerank pool | In top-25 context | Questions |
| --- | --- | --- | --- |
| dense + graph | yes | yes | 88 (54 in top 5) |
| dense only | yes | yes | 9 |
| **graph only** | yes | **dropped** | **34** |
| graph only | yes | yes | 10 (5 in top 5) |
| dense + graph | yes | dropped | 1 |
| neither | no | no | 8 |

Of the 44 graph-only last-hop paragraphs, **29 of the 34 dropped ones had cross-encoder
rank ≤ 25 in the pool**. Nine were in the cross-encoder's top 5, and 2 of those 9 still did
not make the top 25. The cause is the arithmetic of the final score:

1. `final = 0.6 * signal + 0.4 * minmax(ce)` for the `mixed` profile. The query classifier
   is off in the harness; in production any profile can apply.
2. bge-reranker-v2-m3 outputs sigmoid probabilities that are extremely skewed. In the median
   question, 77% of the pool scores below 0.01, and even a gold hop-0 paragraph can get
   0.0002 (the "Ulrich Walter" question). Min-max therefore maps everything below the top 1
   to 3 candidates to about 0, so the **tail order is decided by the signal score**.
3. The signal score of a graph-only candidate is **0**. `mixed` has `graph_weight = 0.0`,
   the dense term is 0 for a candidate dense did not return, and `balance` is 0 because all
   candidates share one source type. So graph-only candidates sort last and fall off at k.

The signal score also lives on unrelated scales. Dense RRF values are ≤ 2/61 ≈ 0.033. PPR
emits probability mass, and BFS emits a constant 1.0. This is the scale mismatch that
PhaseGraph (arXiv 2603.28886) documents for PPR versus dense.

Control, by offline replay of the same candidates: ranking by the cross-encoder alone raises
both-gold-in-context from 105 to 132, with no gain in R@5 (65.0 vs 66.7). The ceiling is 142,
since 8 last hops are in no channel. **27 of the 37 lost questions are lost to the blend,
not to missing graph evidence**, and any rank-based use of the cross-encoder recovers them.

### 2.2 The oracle graph leaks the answer through its topology

In the oracle graph, supporting paragraphs mention their title plus decomposition
subjects and answers, while distractors mention only their title:

| `musique-dev` documents | avg. entities | avg. document neighbours | isolated (no neighbour) |
| --- | --- | --- | --- |
| supporting (250) | 2.45 | 1.78 | **0** |
| distractors (2,078) | 1.00 | 0.18 | **1,918 (92%)** |

"The graph returns this document" is therefore close to "this document is gold". Any fusion
that trusts the graph more looks excellent on this graph:

| `musique-dev`, 150 q, oracle graph | both in ctx | last hop in ctx | R@2 | R@5 | R@10 | last hop @5 |
| --- | --- | --- | --- | --- | --- | --- |
| off (no graph), signal (real run) | 95 | 97 | 54.67 | 65.00 | 74.33 | 55 |
| bfs, signal (real) | 102 | 104 | 55.00 | 66.33 | 76.33 | 59 |
| ppr, signal (real) | 105 | 107 | 55.00 | 66.67 | 77.00 | 60 |
| ppr-novel, signal (real) | 109 | 111 | 55.33 | 67.33 | 77.67 | 62 |
| **ppr, rrf (real)** | **140** | **142** | **60.67** | **84.67** | **91.33** | **108** |
| ppr, CE only (replay) | 132 | 136 | 54.00 | 65.00 | 77.33 | 61 |
| ppr, calibrated (replay) | 120 | 122 | 67.67 | 81.33 | 84.67 | 98 |
| ppr-novel, rrf (replay) | 146 | 148 | 63.00 | 83.33 | 95.33 | 111 |
| ppr-novel, calibrated (replay) | 142 | 144 | 68.00 | 88.00 | 95.00 | 119 |
| bfs, rrf (replay) | 121 | 123 | 65.33 | 77.33 | 85.33 | 91 |
| bfs, calibrated (replay) | 121 | 123 | 67.00 | 80.33 | 85.00 | 97 |
| ppr, learned LR, 5-fold CV | 140 | 142 | 79.00 | 92.67 | 95.00 | 133 |

Compared with ppr+signal, ppr+rrf gains +18.0 R@5 (95% CI 13.7 to 22.7, 54 wins / 3 losses)
and +23.3 points of both-in-context (35 / 0). The query-conditioned LR features add nothing
over static ones here.

**These numbers must not be read as a fusion result.** A cross-validated logistic
regression reaching 92.7 R@5 on 150 questions shows how much gold signal the oracle topology
carries. The same caveat applies to the oracle-graph numbers in `REPORT.md`, for example
PPR last hop 135/150, which are upper bounds inflated by this effect. Fusion must be
selected and evaluated on extracted graphs. The oracle workspace remains useful to check
mechanics (for example, that graph-only candidates survive).

### 2.3 Pilot: chain-conditioned cross-encoder scoring

20 questions from `dev_2hop.jsonl`. The **gold** hop-0 paragraph is the anchor, and the
last-hop paragraph is ranked against 6 of the question's own distractors. Table value: rank
of the gold last hop among 7.

| scoring | mean rank | rank 1 |
| --- | --- | --- |
| CE(q, p), production | 2.70 | 7/20 |
| CE(q, anchor ⊕ p), chain as one passage | 3.45 | 6/20 |
| CE(q ⊕ anchor, p), conditional (`bridge` uses this) | 2.35 | 11/20 |

Conditioning helps on average but is noisy: 4 questions get worse, and for "Ulrich Walter"
a "John Deere World Headquarters" distractor jumps to 0.53. In the pipeline the anchor is
chosen automatically, and a weak `P(anchor)` scales the chain score down. Expect a small
effect; this has not been measured end to end yet.

### 2.4 Literature considered

| Approach | Idea | Fit for Metronix | Status |
| --- | --- | --- | --- |
| HippoRAG 2 (arXiv 2502.14802) | Fusion inside the walk: passage nodes get dense scores as reset probability (×0.05), query-to-triple seeds, LLM triple filter, PPR damping 0.5, PPR output is the ranking | Needs triple embeddings and an extra LLM call per query; `REPORT.md` §6 found anchor teleport hurt the channel | Not implemented; published numbers used as reference |
| Weighted RRF (Cormack 2009) | Rank-level fusion, scale-free | Drop-in | `rrf` |
| Calibrated convex combination (Bruch et al. TOIS 2023, TM2C2; PhaseGraph arXiv 2603.28886) | Normalise per channel, then convex mix; PhaseGraph finds normalisation matters more than the operator and gains over vector-only are small and fragile | Drop-in | `calibrated` |
| Query-conditioned weights (DAT arXiv 2503.23013: LLM judges top-1 per retriever; MoR EMNLP 2025: training-free confidence signals) | Per-query channel weights | DAT costs an LLM call per query; MoR's signals need corpus clustering | Offline only (`fusion_learned.py --features query`); no gain on the oracle graph |
| Chain / set-aware reranking (MDR, PathRetriever, Beam Retrieval, SetCE and DualView 2025-26) | Score a passage conditioned on the passage that led to it | Zero-shot with the existing cross-encoder | `bridge` |
| GraphRAG local search | Fixed context shares per source (quota) | Trivial, crude | Not implemented |

Published passage recall on the HippoRAG MuSiQue set (1,000 q, 11,656 passages):

| | R@2 | R@5 |
| --- | --- | --- |
| Contriever | 34.8 | 46.6 |
| ColBERTv2 | 37.9 | 49.2 |
| HippoRAG (ColBERTv2) | 40.9 | 51.9 |
| NV-Embed-v2 (7B) | — | 69.7 |
| HippoRAG 2 (NV-Embed-v2 + Llama-3.3-70B) | — | 74.7 |
| PropRAG (as cited in arXiv 2603.28886) | — | 78.3 |

For 2Wiki the corresponding R@5 values are 57.5 (Contriever), 89.1 (HippoRAG), 76.5
(NV-Embed-v2) and 90.4 (HippoRAG 2). The gain of the graph method over its own dense
retriever is the comparable quantity (HippoRAG 2: +5.0 R@5 on MuSiQue, +13.9 on 2Wiki),
because Metronix's embedder (nomic-embed-text, 137M) is far weaker than NV-Embed-v2.

## 3. What remains

State of background jobs when this note was written (all lost with the container):

- `run_matrix.sh` on `musique-dev`: 2 of 14 variant runs finished (`ppr:signal`, `ppr:rrf`).
- `musique-llm` LLM graph extraction: 16 of 535 documents; its Qdrant points (535) were
  loaded.
- `musique-hipporag` load: about 600 of 11,656 passages in Qdrant; OpenIE graph not written
  yet.

Next steps, in order:

1. **Finish `musique-dev`**: `{off,bfs,ppr,ppr-novel} x {rrf,calibrated,bridge}`, reusing
   `results/2026-09-26/ce_cache.jsonl`. `off` x new modes is the control for "gain without
   graph evidence".
2. **`musique-llm`** (qwen2.5:3b graph, 30 q): build the graph (§4), then the full matrix.
   n = 30 is small, so report counts with the sign test and do not select on it.
3. **HippoRAG MuSiQue-1000 with the Llama-3.3-70B OpenIE graph**: the decisive,
   non-oracle, literature-comparable test.
   - The defaults are already fixed. Split the questions into two halves by index parity:
     choose the mode (and any weight change) on one half, confirm on the other. Also report
     all 1,000, and the 934 that exclude the 66 questions overlapping the 150 dev slice
     (their qids are in `data/manifest.jsonl`; use `compare_runs.py --exclude`).
   - Configurations: `off:signal` with `RERANKER_ENABLED=false` (our dense retriever R@2/R@5,
     against Contriever / NV-Embed-v2), `off:signal`, `ppr:signal`, `ppr-novel:signal`, and
     the new modes with `ppr` and `ppr-novel`, plus `off` controls.
   - Break results down by hop count (`compare_runs.py --hops 2|3|4`).
   - Compare the gain over our own dense baseline with HippoRAG 2's +5.0 R@5.
4. **2Wiki**: the HippoRAG repository ships the 2Wiki questions and corpus but no OpenIE
   output. Options: extract with qwen2.5:3b (6,119 passages at about 45 s each on 2 cores,
   roughly 3 days on CPU, so a GPU or API model is needed), or a non-LLM title-mention graph
   (label it as such).
5. **PR to #497** only if a mode wins on the confirmation half of the non-oracle set,
   stays significant after excluding the tuning-slice overlap, and does not lose on the
   `off` control. Otherwise report the negative result. The mechanism fix in §2.1 (rank the
   cross-encoder instead of min-max blending) may be worth a PR on its own; it needs the
   same held-out check.

## 4. How the stack was brought up (CPU container, 4 cores, 16 GB)

```bash
dockerd > /tmp/dockerd.log 2>&1 &            # daemon was not running
docker run -d --name mx-qdrant -p 6333:6333 -p 6334:6334 -v mx_qdrant:/qdrant/storage qdrant/qdrant:v1.18.0
docker run -d --name mx-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/metronix_dev \
  -e NEO4J_server_memory_heap_max__size=3G -e NEO4J_server_memory_pagecache_size=1G \
  -v mx_neo4j:/data neo4j:5.26-community
# Ollama needs the egress proxy and its CA to pull models, hence host networking:
docker run -d --name mx-ollama --network host -e HTTPS_PROXY=$HTTPS_PROXY \
  -e SSL_CERT_FILE=/etc/ssl/certs/proxy-ca.crt -v <proxy CA bundle>:/etc/ssl/certs/proxy-ca.crt:ro \
  -v mx_ollama:/root/.ollama ollama/ollama:latest          # 0.34.4
docker exec mx-ollama ollama pull nomic-embed-text && docker exec mx-ollama ollama pull qwen2.5:3b
# second Ollama for graph extraction only, pinned to 2 cores
docker run -d --name mx-ollama-llm --cpuset-cpus=2,3 -p 11435:11434 -v mx_ollama:/root/.ollama ollama/ollama:latest

uv venv --python /usr/bin/python3.13 .venv
uv pip install --python .venv/bin/python -e ".[dev]" torch \
  --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match

export NEO4J_HOST=localhost NEO4J_PORT=7687 NEO4J_USER=neo4j NEO4J_PASSWORD=metronix_dev
export QDRANT_HOST=localhost OLLAMA_HOST=http://localhost:11434 SPLADE_ENABLED=true SPLADE_SERVICE_URL=
```

Pitfalls, which cost most of the first hours:

- **Thread oversubscription kills CPU throughput.** Ollama uses 4 threads even inside a
  2-CPU cpuset, and torch uses 4. Running the cross-encoder, SPLADE and Ollama together made
  35 cross-encoder pairs take 58 s instead of 5 s, and the first qwen extraction timed out
  at 300 s. Fixes:
  - Pin with `--cpuset-cpus` / `taskset`.
  - Set `OMP_NUM_THREADS` for Python.
  - Recreate the Ollama models with a thread cap under the same name, for example
    `FROM qwen2.5:3b` + `PARAMETER num_thread 2` via `ollama create qwen2.5:3b -f Modelfile`.
    The same works for nomic-embed-text (with `num_ctx 8192`); embeddings were checked
    identical to the stored vectors, cosine 1.0.
- Graph extraction goes to the second Ollama with `OLLAMA_LLM_HOST=http://localhost:11435`.
  To resume an interrupted `convert --graph llm`, run it **without `--reset` and with
  `--skip-qdrant`**; otherwise the collection is wiped or duplicated.
- Scripts other than `pipeline_probe` print every structlog debug line. Wrap them with
  `structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))`.
- Postgres is not needed; the pipeline logs `postgres.*.store_failed` and continues.

Build commands:

```bash
python -m benchmarks.musique.scripts.convert --workspace musique-dev --reset      # 2,328 docs, ~25 min
OLLAMA_LLM_HOST=http://localhost:11435 python -m benchmarks.musique.scripts.convert \
  --graph llm --workspace musique-llm --label-prefix musique-llm --limit 30 \
  --manifest benchmarks/musique/data/manifest_llm30.jsonl --reset                # 535 docs
git clone --depth 1 https://github.com/OSU-NLP-Group/hipporag <dir>
python -m benchmarks.musique.scripts.hipporag_set --hipporag-dir <dir> \
  --workspace musique-hipporag --label-prefix mhr --graph openie \
  --manifest benchmarks/musique/data/manifest_hipporag.jsonl --reset --workers 2
RUNS_DIR=benchmarks/musique/results/local CE_CACHE=benchmarks/musique/results/2026-09-26/ce_cache.jsonl \
  benchmarks/musique/scripts/run_matrix.sh musique-dev benchmarks/musique/data/manifest.jsonl 150 dev \
  "off:rrf off:calibrated off:bridge ppr:calibrated ppr:bridge ppr-novel:rrf ppr-novel:calibrated ppr-novel:bridge"
```

`hipporag_set.py --dry-run` summary: 1,000 questions (518 two-hop, 316 three-hop, 166
four-hop); 11,656 passages; every gold passage is in the corpus; OpenIE yields 86,919
canonical entities, 138,988 mentions and 140,612 triples.

Measured costs on this machine:

| Step | Cost |
| --- | --- |
| Loading, 4 cores | ~1.8 docs/s (Ollama embedding 0.16 s + SPLADE 0.11 s per doc) |
| Loading, 2 cores shared | ~1 doc/s |
| Cross-encoder, 4 threads uncontended | 0.15 s/pair (~5 s per query for a 30 to 35 candidate pool) |
| Pipeline run, 150 q | ~20 min uncached, ~5 min cached |
| qwen2.5:3b extraction, 2 threads | ~45 s/doc (6 tok/s generation, ~150 output tokens) |
