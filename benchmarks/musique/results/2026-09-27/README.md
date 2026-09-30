# Runs for the #497 fusion research note

`pipeline_probe` results behind §5.5-§5.7, §5.10 and §5.11 of
`../../findings/2026-09-26-fusion-research-note.md`, one gzipped JSON per dataset:
`{run name: {"summary": ..., "rows": [per question: qid, gold, retrieved_rank,
context_rank, context_hop0, context_last_hop, context_both, and for traced runs
pool_gold, pool_graph_only_gold, pool_size]}}`. Candidate dumps are left out (tens of
MB); rerun with `--trace` to regenerate them. The pool fields are what
`pool_coverage.py` needs for the candidate-pool numbers of the note (§5.5-§5.7).

Run names: `<half>[-<group>]_<graph>_<fusion>`.

- half: `tune` (even question index), `confirm` (odd), `all` (2Wiki, 1,000 questions),
  `dev` (the 150-question oracle-graph slice, `musique_dev_oracle_runs.json.gz`);
  `llm` (the first 30 dev questions on the qwen2.5:3b graph, `musique_llm_qwen_runs.json.gz`;
  graph enrichment on, as for `dev`);
- group: none = production channel settings; `pprplus` = PPR with
  `SUBGRAPH=specific`, `TELEPORT=ranked`, anchors excluded; `ceonly` = `rrf` with
  weights `rerank=1,dense=0,graph=0,metadata=0`; `dense` = `RERANKER_ENABLED=false`;
  `abl-<settings>` (qwen slice only, §5.11) = one "ppr+" setting at a time: `specific`
  (`SUBGRAPH=specific`), `seeds` / `ranked` (`TELEPORT`), `specific-seeds`, `both`;
  `learned-<channel>_query` = offline replay of the learned fusion (fitted on the MuSiQue
  tune half) on the `signal` dump of that channel;
- `skipped` summaries record configurations that were not run and why.

`compare_runs.py` reads these after `gunzip` + selecting one run, e.g.

```bash
python - <<'PY'
import gzip, json
runs = json.load(gzip.open("hipporag_musique_runs.json.gz", "rt"))
for name in ("confirm_bfs_signal", "confirm-pprplus_ppr-novel_learned"):
    json.dump(runs[name], open(f"/tmp/{name}.json", "w"))
PY
python -m benchmarks.musique.scripts.compare_runs /tmp/confirm_bfs_signal.json \
  /tmp/confirm-pprplus_ppr-novel_learned.json
```
