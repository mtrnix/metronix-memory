#!/usr/bin/env python3
"""Evaluate LongMemEval JSONL results using the vendored judge script."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BENCH_ROOT = SCRIPT_DIR.parent
VENDOR_EVAL = BENCH_ROOT / "vendor" / "evaluate_qa.py"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import dataset as lme_dataset  # noqa: E402
from env_config import BenchConfig, load_dotenv, validate_judge_env  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LongMemEval LLM judge evaluation")
    parser.add_argument("--results", required=True, help="Hypothesis JSONL file")
    parser.add_argument("--variant", choices=["oracle", "s"], default="s")
    parser.add_argument("--judge-model", help="Override LME_JUDGE_MODEL")
    parser.add_argument("--judge-base-url", help="Override LME_JUDGE_BASE_URL")
    parser.add_argument("--judge-api-key", help="Override LME_JUDGE_API_KEY")
    args = parser.parse_args()

    load_dotenv()
    config = BenchConfig.from_env(load_files=False).apply_cli_overrides(
        judge_api_key=args.judge_api_key,
        judge_base_url=args.judge_base_url,
        judge_model=args.judge_model,
    )
    if not config.judge_api_key:
        print("ERROR: LME_JUDGE_API_KEY (or LME_CHAT_API_KEY / OPENAI_API_KEY) is required")
        return 1

    for message in validate_judge_env(config):
        print(f"ERROR: {message}")
        return 1

    print(f"Judge config: model={config.judge_model} base_url={config.judge_base_url}")

    try:
        ref_file = lme_dataset.verify_dataset(args.variant)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1
    except ValueError as exc:
        print(f"ERROR: reference dataset failed verification: {exc}")
        return 1

    if not VENDOR_EVAL.exists():
        print(f"ERROR: vendored evaluator missing: {VENDOR_EVAL}")
        return 1

    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["OPENAI_API_KEY"] = config.judge_api_key
    env["LME_JUDGE_API_KEY"] = config.judge_api_key
    env["LME_JUDGE_BASE_URL"] = config.judge_base_url
    env["LME_JUDGE_MODEL"] = config.judge_model

    cmd = [
        sys.executable,
        str(VENDOR_EVAL),
        "--results",
        args.results,
        "--reference",
        str(ref_file),
        "--judge-model",
        config.judge_model,
        "--judge-base-url",
        config.judge_base_url,
        "--judge-api-key",
        config.judge_api_key,
    ]
    print("Running:", " ".join(cmd))
    completed = subprocess.run(cmd, env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
