#!/usr/bin/env bash
# Reader step of the answer-accuracy note: answer_eval read over the retrieval blocks of
# run_blocks.sh (<cfg>_<offset>.json.gz), configurations A then B per block. Each block's
# answers are gzipped when it finishes; existing ones are skipped, so an interrupted run
# resumes at the next block (answer_eval also resumes inside a block).
#
#   benchmarks/musique/scripts/read_blocks.sh <blocks_dir> <total> <manifest> \
#       <dataset.json> <corpus.json> <label_prefix> <prompt_cache>
#
# Environment: BLOCK (default 50), PYTHON (default .venv/bin/python).
set -euo pipefail
DIR=$1; TOTAL=$2; MAN=$3; DATASET=$4; CORPUS=$5; PREFIX=$6; CACHE=$7
BLOCK=${BLOCK:-50}
PY=${PYTHON:-.venv/bin/python}
for ((off = 0; off < TOTAL; off += BLOCK)); do
  for cfg in A B; do
    name=$(printf "%s_%04d" "$cfg" "$off")
    out=$DIR/answers_$name.jsonl
    if [ -f "$out.gz" ]; then continue; fi
    start=$(date +%s)
    run=$(mktemp --suffix=.json)
    gunzip -c "$DIR/$name.json.gz" > "$run"
    "$PY" -m benchmarks.musique.scripts.answer_eval read --run "$run" --manifest "$MAN" \
      --dataset "$DATASET" --corpus "$CORPUS" --label-prefix "$PREFIX" \
      --expect-digest 357c53fb659c --output "$out" --prompt-cache "$CACHE" \
      > "$DIR/answers_$name.log" 2>&1
    rm -f "$run"
    gzip -f "$out"
    echo "read $name $(( $(date +%s) - start ))s $(date +%T)"
  done
done
