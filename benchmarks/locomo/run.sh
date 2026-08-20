#!/usr/bin/env bash
set -euo pipefail

bench_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$bench_root"

if [[ ! -x .venv/bin/python ]]; then
  echo "Run ./setup.sh first." >&2
  exit 2
fi

mode=""
categories="1,2,3,4"
max_questions=""
output=""
force=0
while (($#)); do
  case "$1" in
    --retrieval-mode) mode="${2:?missing retrieval mode}"; shift 2 ;;
    --categories) categories="${2:?missing categories}"; shift 2 ;;
    --max-questions) max_questions="${2:?missing maximum}"; shift 2 ;;
    --output) output="${2:?missing output}"; shift 2 ;;
    --force) force=1; shift ;;
    --smoke) max_questions=3; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ "$mode" != "flag-off" && "$mode" != "flag-on" ]]; then
  echo "Use --retrieval-mode flag-off or --retrieval-mode flag-on." >&2
  exit 2
fi

.venv/bin/python scripts/preflight.py
args=(run --retrieval-mode "$mode" --categories "$categories")
[[ -n "$max_questions" ]] && args+=(--max-questions "$max_questions")
[[ -n "$output" ]] && args+=(--output "$output")
((force)) && args+=(--force)
.venv/bin/python scripts/run_benchmark.py "${args[@]}"

if [[ -n "$output" ]]; then
  results="$output"
else
  results="$(ls -t results/*.jsonl | head -1)"
fi
.venv/bin/python scripts/evaluate.py "$results"
