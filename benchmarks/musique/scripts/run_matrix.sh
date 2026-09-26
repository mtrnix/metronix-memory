#!/usr/bin/env bash
# Run pipeline_probe over a list of graph:fusion configurations, one fresh process each
# (settings are read at import time). Existing outputs are skipped, so an interrupted
# matrix resumes.
#
#   benchmarks/musique/scripts/run_matrix.sh <workspace> <manifest> <limit> <tag> \
#       "ppr:signal ppr:rrf off:calibrated ..." [extra pipeline_probe args]
#
# Environment: RUNS_DIR (default benchmarks/musique/results/local), CE_CACHE (default
# $RUNS_DIR/ce_cache.jsonl), CPUS (taskset list, default all), THREADS (torch threads).
set -euo pipefail
WS=$1; MAN=$2; LIM=$3; TAG=$4; CONFIGS=$5; shift 5
RUNS_DIR=${RUNS_DIR:-benchmarks/musique/results/local}
CE_CACHE=${CE_CACHE:-$RUNS_DIR/ce_cache.jsonl}
PY=${PYTHON:-.venv/bin/python}
mkdir -p "$RUNS_DIR"
PIN=()
if [ -n "${CPUS:-}" ]; then PIN=(taskset -c "$CPUS"); fi
for cfg in $CONFIGS; do
  g=${cfg%%:*}; f=${cfg##*:}
  out=$RUNS_DIR/${TAG}_${g}_${f}.json
  if [ -f "$out" ]; then echo "skip $out"; continue; fi
  OMP_NUM_THREADS=${THREADS:-4} "${PIN[@]}" "$PY" -m benchmarks.musique.scripts.pipeline_probe \
    --workspace "$WS" --manifest "$MAN" --limit "$LIM" --graph "$g" --fusion "$f" --trace \
    --rerank-cache "$CE_CACHE" --output "$out" "$@" > "$RUNS_DIR/${TAG}_${g}_${f}.log" 2>&1
  echo "done $out $(date +%T)"
done
