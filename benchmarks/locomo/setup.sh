#!/usr/bin/env bash
set -euo pipefail

bench_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$bench_root"

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-bench.txt
if [[ ! -f .env.benchmark ]]; then
  cp .env.benchmark.example .env.benchmark
  echo "Created $bench_root/.env.benchmark; add the required keys, then rerun setup."
  exit 1
fi
.venv/bin/python scripts/run_benchmark.py download
.venv/bin/python scripts/preflight.py --ensure-workspace
