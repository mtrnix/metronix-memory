#!/usr/bin/env python3
"""Validate LoCoMo configuration, dataset, Metronix health, and workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BENCH_ROOT = SCRIPT_DIR.parent
REPO_ROOT = BENCH_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.locomo.scripts.dataset import DATASET_SHA256, load_dataset, sha256  # noqa: E402
from benchmarks.locomo.scripts.env_config import DEFAULT_ENV_PATH, BenchConfig  # noqa: E402
from benchmarks.longmemeval.scripts.metronix_client import MetronixRestClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="LoCoMo benchmark preflight")
    parser.add_argument("--check-env-only", action="store_true")
    parser.add_argument("--ensure-workspace", action="store_true")
    args = parser.parse_args()
    try:
        config = BenchConfig.from_env()
    except ValueError as exc:
        print(f"ERROR: invalid configuration: {exc}")
        return 1
    print("Configuration (secret values hidden):")
    print(f"  env file: {DEFAULT_ENV_PATH}")
    print(f"  workspace: {config.workspace_id}")
    print(f"  chat: {config.chat_model} @ {config.chat_base_url}")
    print(f"  top_k: {config.retrieve_top_k}")
    if missing := config.missing():
        print("ERROR: missing: " + ", ".join(missing))
        return 1
    if args.check_env_only:
        return 0
    dataset_path = BENCH_ROOT / "data" / "locomo10.json"
    try:
        load_dataset(dataset_path)
        if sha256(dataset_path) != DATASET_SHA256:
            raise ValueError("SHA-256 mismatch")
        print(f"  dataset: verified ({DATASET_SHA256})")
    except ValueError as exc:
        print(f"ERROR: dataset validation failed: {exc}")
        return 1
    rest = MetronixRestClient(api_url=config.metronix_api_url)
    try:
        print(f"  Metronix: {rest.health().get('status', 'healthy')}")
        if args.ensure_workspace:
            rest.ensure_workspace(
                config.workspace_id,
                name="LoCoMo benchmark",
                description="Isolated LoCoMo benchmark workspace",
            )
        if config.workspace_id not in {
            item.get("workspace_id") for item in rest.list_workspaces()
        }:
            raise ValueError(f"workspace {config.workspace_id} does not exist")
    except Exception as exc:
        print(f"ERROR: Metronix preflight failed: {exc}")
        return 1
    print("Preflight OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
