#!/usr/bin/env python3
"""Aggregate the per-row recall@k the LongMemEval runner wrote.

The runner records ``recall_at_5`` / ``recall_at_10`` and
``recall_gate_eligible`` on every answers-JSONL row. This step sums them into
``<results>.retrieval.eval.json`` — no LLM calls, no cost. The LLM-judge answer
accuracy stays in ``evaluate_results.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks._shared import retrieval_eval  # noqa: E402


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"result line {number} is not an object")
        rows.append(row)
    return rows


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate LongMemEval retrieval recall@k")
    parser.add_argument("--results", required=True, type=Path, help="Answers JSONL file")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = load_jsonl(args.results)
    if not any("recall_gate_eligible" in r for r in rows):
        print(
            "ERROR: results have no recall fields — they predate the recall harness. "
            "Re-run with --force."
        )
        return 1

    report = retrieval_eval.aggregate_recall(rows, group_key="question_type")
    output = args.output or args.results.with_suffix(args.results.suffix + ".retrieval.eval.json")
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    r10 = retrieval_eval.gate_value(report, k=10)
    r5 = retrieval_eval.gate_value(report, k=5)
    print(
        f"LongMemEval  recall@10={_fmt(r10)}  recall@5={_fmt(r5)}  "
        f"({report['eligible_count']}/{report['question_count']} recall-eligible)"
    )
    for name, group in report["by_group"].items():
        print(f"    {name}: recall@10={_fmt(group['recall'].get('10'))} ({group['count']})")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
