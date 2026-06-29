#!/usr/bin/env bash
# LongMemEval benchmark run (Linux / macOS / Git Bash)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
if [[ -x "$VENV/Scripts/python.exe" ]]; then
  PYTHON="$VENV/Scripts/python.exe"
elif [[ -x "$VENV/bin/python" ]]; then
  PYTHON="$VENV/bin/python"
else
  echo "Virtual environment not found. Run ./setup.sh or .\\setup.ps1 first."
  exit 1
fi

SMOKE=0
RUN_ONLY=0
MAX_QUESTIONS=""
VARIANT="s"
FORCE=0

usage() {
  cat <<'EOF'
Usage: ./run.sh [options]

Options:
  --smoke            Run oracle variant with 3 questions (pipeline check)
  --run-only         Skip LLM judge evaluation
  --max-questions N  Limit number of questions
  --variant oracle|s Dataset variant (default: s)
  --force            Delete output file before run
  -h, --help         Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke) SMOKE=1; shift ;;
    --run-only) RUN_ONLY=1; shift ;;
    --max-questions) MAX_QUESTIONS="$2"; shift 2 ;;
    --variant) VARIANT="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "run.sh requires bash."
  echo "On Windows PowerShell use: .\\run.ps1 -Smoke"
  exit 1
fi

if [[ "$SMOKE" -eq 1 ]]; then
  VARIANT="oracle"
  MAX_QUESTIONS="${MAX_QUESTIONS:-3}"
fi

echo "==> Preflight"
"$PYTHON" scripts/preflight.py --ensure-workspace

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT="$ROOT/results/${TIMESTAMP}_${VARIANT}.jsonl"
mkdir -p "$ROOT/results"

RUN_ARGS=(run --variant "$VARIANT" --output "$OUTPUT")
if [[ -n "$MAX_QUESTIONS" ]]; then
  RUN_ARGS+=(--max-questions "$MAX_QUESTIONS")
fi
if [[ "$FORCE" -eq 1 ]]; then
  RUN_ARGS+=(--force)
fi

echo "==> Running benchmark -> $OUTPUT"
"$PYTHON" scripts/run_benchmark.py "${RUN_ARGS[@]}"

if [[ ! -f "$OUTPUT" ]]; then
  echo "Expected output file not found: $OUTPUT"
  exit 1
fi

echo ""
echo "Results: $OUTPUT"

if [[ "$RUN_ONLY" -eq 0 ]]; then
  echo "==> Evaluation (LLM judge)"
  "$PYTHON" scripts/evaluate_results.py --results "$OUTPUT" --variant "$VARIANT"
fi

echo "Done."
