# Multi-hop retrieval: MuSiQue and 2Wiki (passage recall@5)

Source of the README table "Retrieval (passage recall@5), reproducible". Full method,
statistics and limitations: [research note](../../benchmarks/musique/findings/2026-09-26-fusion-research-note.md)
(§5.6 MuSiQue confirm half, §5.7 2Wiki, §5.8 published baselines, §7 limitations).

| Configuration | Run name in the results file | MuSiQue R@5 (500 held-out) | 2Wiki R@5 (1,000) |
| --- | --- | --- | --- |
| Production defaults | `confirm_bfs_signal` / `all_bfs_signal` | 58.25 | 71.85 |
| Opt-in learned "ppr+" (online pipeline) | `confirm-pprplus_ppr-novel_learned` / `all-pprplus_ppr-novel_learned` | 62.80 | 85.65 |

R@5 follows the HippoRAG definition: per question, the fraction of gold passages ranked in
the top 5, averaged over questions. The research note rounds these to one decimal
(58.25 appears there as both 58.2 and 58.3); the table keeps the exact values.

## Check the numbers from the committed files

No stack or models needed:

```bash
cd benchmarks/musique/results/2026-09-27
python3 - <<'PY'
import gzip, json
for path, names in (
    ("hipporag_musique_runs.json.gz", ["confirm_bfs_signal", "confirm-pprplus_ppr-novel_learned"]),
    ("hipporag_2wiki_runs.json.gz", ["all_bfs_signal", "all-pprplus_ppr-novel_learned"]),
):
    runs = json.load(gzip.open(path, "rt"))
    for name in names:
        rows = runs[name]["rows"]
        r5 = sum(
            sum(1 for rank in r["retrieved_rank"].values() if rank is not None and rank <= 5)
            / len(r["retrieved_rank"])
            for r in rows
        ) / len(rows)
        print(f"{name}: n={len(rows)} R@5={100 * r5:.2f}")
PY
```

## Reproduce the runs

From §8 of the research note (needs the local Neo4j + Qdrant stack, `nomic-embed-text` in
Ollama, the SPLADE model, and `bge-reranker-v2-m3` on first use; CPU-only loading takes
about 2 h on 4 cores):

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

§8 spells out the MuSiQue runs only. For 2Wiki the note says "ppr+" runs with the MuSiQue
settings (§5.7), so the corresponding runs are the same two `pipeline_probe` commands with
`--workspace wiki2-hipporag`, `--manifest <out>/manifest_2wiki.jsonl` and `--limit 1000`
(adapted here, not copied from the note). The learned model is the one fitted on the
MuSiQue tune half; nothing was fitted on 2Wiki.

## Caveats

- "ppr+" (`--graph ppr-novel` with `SUBGRAPH=specific`, `TELEPORT=ranked`) and
  `--fusion learned` are opt-in. Defaults: `METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED=false`,
  `METRONIX_RETRIEVAL_FUSION_MODE=signal`, `METRONIX_RETRIEVAL_GRAPH_PPR_SUBGRAPH=paths`,
  `METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT=subgraph`.
- Passage recall, not answer accuracy: no reader, EM or F1 was run.
- The MuSiQue graph is HippoRAG's released OpenIE graph, extracted by Llama-3.3-70B.
  A graph extracted by Metronix's own pipeline (`qwen2.5:3b` on CPU) was measured only on
  the first 30 questions of the dev slice (535 passages). It is much sparser: the PPR
  channel alone reaches the last-hop passage for 9 of 30 questions vs 29 of 30 on the
  oracle graph ([REPORT](../../benchmarks/musique/REPORT.md), item 7). End to end on that
  slice, learned "ppr+" is +13.3 R@5 over production `bfs:signal` (95% CI 3.3 to 23.3,
  10 wins / 2 losses; research note §5.10), and the note itself calls the slice "a
  consistency check on a small, sparse graph, not evidence of the size of the gain".
- The 2Wiki title-mention graph favours gold passages structurally (research note §5.2:
  14.7% of gold passages isolated vs 60.1% of distractors), so the 2Wiki gain is optimistic;
  MuSiQue is the conservative estimate.
- The learned fusion was fitted on the MuSiQue tune half (the other 500 questions). Single
  run, CPU only; LLM calls in the harness are stubbed and post-rerank graph enrichment is
  skipped (checked not to affect ranking on samples, §7).
- Published baselines quoted in §5.8: HippoRAG 2 reaches 74.7 (MuSiQue) and 90.4 (2Wiki);
  plain NV-Embed-v2 reaches 69.7 on MuSiQue. Both Metronix rows are below these.
