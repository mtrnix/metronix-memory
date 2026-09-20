#!/usr/bin/env bash
# LongMemEval benchmark setup (Linux / macOS / Git Bash)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"
ENV_BENCHMARK="$ROOT/.env.benchmark"
ENV_EXAMPLE="$ROOT/.env.benchmark.example"
LEGACY_ENV="$ROOT/.env"

echo "==> LongMemEval setup"

if [[ ! -f "$ENV_BENCHMARK" ]]; then
  if [[ -f "$LEGACY_ENV" ]]; then
    cp "$LEGACY_ENV" "$ENV_BENCHMARK"
    echo "Migrated benchmarks/longmemeval/.env -> .env.benchmark"
  else
    cp "$ENV_EXAMPLE" "$ENV_BENCHMARK"
    echo "Created .env.benchmark from .env.benchmark.example - edit it before running."
  fi
fi

if [[ ! -d "$VENV" ]]; then
  echo "==> Creating virtual environment"
  "$PYTHON" -m venv "$VENV"
fi

if [[ -x "$VENV/Scripts/python.exe" ]]; then
  VENV_PYTHON="$VENV/Scripts/python.exe"
  # shellcheck disable=SC1091
  source "$VENV/Scripts/activate"
elif [[ -x "$VENV/bin/python" ]]; then
  VENV_PYTHON="$VENV/bin/python"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
else
  echo "Virtual environment not found after creation."
  exit 1
fi

"$VENV_PYTHON" -m pip install -q --upgrade pip
"$VENV_PYTHON" -m pip install -q -r requirements-bench.txt

echo "==> Downloading datasets (oracle + s)"
"$VENV_PYTHON" scripts/run_benchmark.py download --variant oracle
"$VENV_PYTHON" scripts/run_benchmark.py download --variant s

echo "==> Preflight (health, env, workspace MABENCH)"
"$VENV_PYTHON" scripts/preflight.py --ensure-workspace

echo ""
echo "Setup complete."
echo "Next: edit benchmarks/longmemeval/.env.benchmark if needed, then run ./run.sh --smoke"
