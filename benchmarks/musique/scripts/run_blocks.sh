#!/usr/bin/env bash
# Retrieval for the answer-accuracy note (findings/2026-09-30-answer-accuracy-note.md):
# configurations A (production bfs:signal) and B (learned + "ppr+") over a manifest, in
# blocks of BLOCK questions, one fresh pipeline_probe process per block and configuration.
# Each block's output is gzipped when it finishes; existing blocks are skipped, so an
# interrupted run resumes at the next block.
#
#   benchmarks/musique/scripts/run_blocks.sh <workspace> <manifest> <total> <out_dir> <ce_cache>
#
# Environment: BLOCK (default 50), PYTHON (default .venv/bin/python), THREADS (torch threads).
set -euo pipefail
WS=$1; MAN=$2; TOTAL=$3; OUT=$4; CE=$5
BLOCK=${BLOCK:-50}
PY=${PYTHON:-.venv/bin/python}
mkdir -p "$OUT"
declare -A ARGS=(
  [A]="--graph bfs --fusion signal"
  [B]="--graph ppr-novel --fusion learned --env METRONIX_RETRIEVAL_GRAPH_PPR_SUBGRAPH=specific --env METRONIX_RETRIEVAL_GRAPH_PPR_TELEPORT=ranked"
)
for ((off = 0; off < TOTAL; off += BLOCK)); do
  for cfg in A B; do
    name=$(printf "%s_%04d" "$cfg" "$off")
    if [ -f "$OUT/$name.json.gz" ]; then continue; fi
    start=$(date +%s)
    # shellcheck disable=SC2086
    OMP_NUM_THREADS=${THREADS:-4} "$PY" -m benchmarks.musique.scripts.pipeline_probe \
      --workspace "$WS" --manifest "$MAN" --offset "$off" --limit "$BLOCK" ${ARGS[$cfg]} \
      --skip-graph-enrichment --keep-top 5 --rerank-cache "$CE" \
      --output "$OUT/$name.json" > "$OUT/$name.log" 2>&1
    gzip -f "$OUT/$name.json"
    echo "done $name $(( $(date +%s) - start ))s $(date +%T)"
  done
done
