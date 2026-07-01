#!/usr/bin/env python3
"""Preflight checks for LongMemEval benchmark runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from env_config import (  # noqa: E402
    DEFAULT_ENV_PATH,
    REPO_ENV_PATH,
    BenchConfig,
    load_dotenv,
    resolved_env_path,
    validate_judge_env,
)  # noqa: E402
from metronix_client import MetronixRestClient  # noqa: E402


def _print_env_status(config: BenchConfig) -> int:
    print("Environment variable status (values are not shown):")
    for key, is_set in config.env_status().items():
        print(f"  {key}: {'set' if is_set else 'MISSING'}")
    missing = [k for k, v in config.env_status().items() if not v]
    if missing:
        print("\nMissing required variables:", ", ".join(missing))
        print(f"Edit benchmark settings in: {DEFAULT_ENV_PATH}")
        if not config.metronix_mcp_api_key and REPO_ENV_PATH.exists():
            print(f"Hint: copy METRONIX_MCP_API_KEY from repo-root {REPO_ENV_PATH}")
        return 1

    env_file = resolved_env_path()
    if env_file:
        print(f"\nBenchmark env file: {env_file}")
    print(
        f"Chat: {config.chat_model} @ {config.chat_base_url}\n"
        f"Judge: {config.judge_model} @ {config.judge_base_url}"
    )
    for message in validate_judge_env(config):
        print(f"\nERROR: {message}")
        return 1

    print("\nAll required variables are set.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LongMemEval preflight checks")
    parser.add_argument("--metronix-url", help="Metronix REST API base URL")
    parser.add_argument("--workspace", help="Benchmark workspace ID")
    parser.add_argument(
        "--ensure-workspace", action="store_true", help="Create workspace if missing"
    )
    parser.add_argument(
        "--check-env-only", action="store_true", help="Only validate .env variables"
    )
    parser.add_argument(
        "--copy-metronix-key-hint", action="store_true", help="Print repo-root key hint"
    )
    args = parser.parse_args()

    load_dotenv()
    config = BenchConfig.from_env(load_files=False)
    api_url = args.metronix_url or config.metronix_api_url
    workspace_id = args.workspace or config.workspace_id

    if args.copy_metronix_key_hint and REPO_ENV_PATH.exists():
        print(f"Copy METRONIX_MCP_API_KEY from: {REPO_ENV_PATH}")

    if args.check_env_only:
        return _print_env_status(config)

    rest = MetronixRestClient(api_url=api_url)
    try:
        health = rest.health()
        print(f"Metronix health: {health.get('status', health)}")
    except Exception as exc:
        print(f"ERROR: Metronix health check failed: {exc}")
        print("Ensure Docker stack is running: docker compose up -d")
        return 1

    env_rc = _print_env_status(config)
    if env_rc != 0:
        return env_rc

    if args.ensure_workspace:
        try:
            created = rest.ensure_workspace(workspace_id)
            if created:
                print(f"Workspace {workspace_id} created.")
            else:
                print(f"Workspace {workspace_id} already present.")
        except Exception as exc:
            print(f"ERROR: Failed to ensure workspace {workspace_id}: {exc}")
            return 1
    else:
        workspaces = {ws.get("workspace_id") for ws in rest.list_workspaces()}
        if workspace_id not in workspaces:
            print(f"WARNING: workspace {workspace_id} not found.")
            print("Run with --ensure-workspace or create it via POST /api/v1/workspaces")
            return 1
        print(f"Workspace {workspace_id} exists.")

    print("Preflight OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
