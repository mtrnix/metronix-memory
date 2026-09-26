# MuSiQue 2-hop graph probe

Loads a slice of MuSiQue-Ans dev into a Metronix workspace with an **oracle graph**
(no LLM extraction) and measures whether the graph channel's BFS reaches the
last-hop paragraph through RELATION expansion. Part of the issue #497 research;
depends on the #508 fix (`get_graph_relationships` projecting endpoint names).

## Graph shape

| MuSiQue | Metronix |
| --- | --- |
| distinct paragraph (supporting and distractor) | Qdrant point + `Document {doc_label: "musique:para:<sha1(title, text)[:16]>"}` |
| paragraph `title` | `Entity`, `(Document)-[:MENTIONS]->(Entity)` |
| decomposition step *i* | `(subject_i)-[:RELATION {type: relation_i, hop: i}]->(answer_i)`, both mentioned by the step's supporting paragraph |

`subject_i` is the answer of step *k* when the sub-question references `#k`, else the
left side of `subject >> relation`, else the paragraph title. Distractors mention
only their title entity and get no RELATION edges. MuSiQue reuses Wikipedia
paragraphs across questions, so the label is content-based: one Document per
distinct paragraph, carrying `qids` (questions it appears in) and
`supporting_qids`. Per-question copies made BFS land on another question's copy
of the gold text and count it as a miss. Each `answer_aliases` entry
becomes `(alias)-[:ALIAS]->(final answer)`; these are aliases of the final answer
only, so they do not help seed matching for `--seeds title`.

## Committed slice

`data/dev_2hop.jsonl` holds the first 150 answerable 2-hop questions of
`musique_ans_v1.0_dev.jsonl` (HF `dgslibisey/MuSiQue`, revision
`c8f4f8c9465fb69d31a8eae894c3fd509c4ca321`; MuSiQue is CC BY 4.0).
`data/manifest.jsonl` is the matching `convert.py` output: 150 questions,
2328 distinct documents (250 supporting; 2999 paragraph occurrences), 2470 entities,
298 RELATION edges (255 distinct), 58 ALIAS edges (38 distinct).

## Run (needs the local Neo4j + Qdrant + embedding stack)

```bash
# 1. slice 150 answerable 2-hop questions (downloads dgslibisey/MuSiQue from HF)
.venv/bin/python -m benchmarks.musique.scripts.dataset --limit 150
#    or from a local file: --input musique_ans_v1.0_dev.jsonl

# 2. build graph + manifest; inspect counts first
.venv/bin/python -m benchmarks.musique.scripts.convert --dry-run
.venv/bin/python -m benchmarks.musique.scripts.convert --workspace musique-dev --reset

# 3. per-hop probe (oracle seeds, then regex title-entity seeds)
.venv/bin/python -m benchmarks.musique.scripts.probe --limit 20 --recall
.venv/bin/python -m benchmarks.musique.scripts.probe --limit 20 --seeds title
```

Add `--dense` to the probe to also run the production `recall_dense` (hybrid
dense + sparse RRF, `recall_top_n_dense`). This needs the stack's embedding path:
Ollama with `nomic-embed-text` (`OLLAMA_HOST`) and SPLADE (`SPLADE_ENABLED=true`;
with `SPLADE_SERVICE_URL` empty the local `naver/splade-cocondenser-ensembledistil`
model is used). Documents must have been loaded with the same settings.

`--reset` wipes the whole `musique-dev` workspace (graph and Qdrant collection);
use a dedicated workspace.

## Reading the probe

Each row reports `gold_found_at_hop`: the BFS hop at which each supporting paragraph
first appeared (0 = directly from a seed, `null` = not found). `last_hop_via_bfs` is
the multi-hop signal: the last-step paragraph was reached only through expansion.
`recall_graph_labels` shows what the real channel returns after its unordered
`limit` cut, which can hide BFS hits; compare it against the per-hop trace.
`--seeds title` exercises `extract_title_entities`; misses there are seeding
problems, not traversal problems.

## Fusion experiments (#497, in progress)

`pipeline_probe.py --fusion {signal,rrf,calibrated,bridge}` selects the opt-in score
fusion (`METRONIX_RETRIEVAL_FUSION_MODE`); `--trace` dumps per-stage gold ranks and every
candidate's channel and cross-encoder scores, `--rerank-cache` reuses cross-encoder
scores. `fusion_replay.py`, `fusion_learned.py` and `compare_runs.py` analyse those dumps;
`hipporag_set.py` loads the HippoRAG MuSiQue-1000 set with its released OpenIE graph;
`run_matrix.sh` runs configuration matrices. Status, findings and the remaining plan:
`findings/2026-09-26-fusion-handoff.md`.
