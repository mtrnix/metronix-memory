#!/usr/bin/env python3
"""Compare two benchmark runs and apply the recall@10 gate.

    python benchmarks/compare_runs.py \\
        BASELINE/answers.jsonl CURRENT/answers.jsonl \\
        --gate recall_at_10=0.60 \\
        --max-regression recall_at_10=0.03

Exit code is 0 only when the two runs are comparable (same dataset bytes, same
question set, same repo revision, clean tree, only the declared retrieval mode
differs) AND every gate / regression check passes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks._shared import compare  # noqa: E402


def _fmt(value: float | None) -> str:
    return "  n/a  " if value is None else f"{value:8.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("baseline", type=Path, help="baseline run's answers.jsonl")
    parser.add_argument("current", type=Path, help="current run's answers.jsonl")
    parser.add_argument(
        "--gate",
        action="append",
        default=[],
        metavar="METRIC=FLOOR",
        help="absolute floor the current run must clear (e.g. recall_at_10=0.6)",
    )
    parser.add_argument(
        "--max-regression",
        action="append",
        default=[],
        metavar="METRIC=DECLINE",
        help="largest permitted drop vs. the baseline (e.g. recall_at_10=0.03)",
    )
    parser.add_argument("--output", type=Path, help="write the JSON comparison report here")
    parser.add_argument("--allow-dirty", action="store_true", help="permit a dirty-tree run")
    parser.add_argument(
        "--allow-same-mode",
        action="store_true",
        help="permit both runs declaring the same retrieval mode (repeatability check)",
    )
    args = parser.parse_args(argv)

    try:
        gates = compare.collect_assignments(args.gate)
        regressions = compare.collect_assignments(args.max_regression)
        baseline = compare.load_run(args.baseline)
        current = compare.load_run(args.current)
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = compare.compare(
        baseline,
        current,
        gates=gates,
        max_regressions=regressions,
        allow_dirty=args.allow_dirty,
        allow_same_mode=args.allow_same_mode,
    )

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    b_mode = report["baseline"]["retrieval_mode"]
    c_mode = report["current"]["retrieval_mode"]
    print(f"baseline [{b_mode}]  vs  current [{c_mode}]")
    print(f"{'metric':<16} {'baseline':>8} {'current':>8} {'delta':>9}")
    for name, m in report["metrics"].items():
        delta = "   n/a" if m["delta"] is None else f"{m['delta']:+9.4f}"
        print(f"{name:<16} {_fmt(m['baseline'])} {_fmt(m['current'])} {delta}")
    print(
        f"recall-eligible: baseline {report['recall_eligible']['baseline']}  "
        f"current {report['recall_eligible']['current']}"
    )

    for reason in report["incompatibilities"]:
        print(f"  NOT COMPARABLE: {reason}", file=sys.stderr)
    for reason in report["gate_failures"]:
        print(f"  GATE FAIL: {reason}", file=sys.stderr)
    for reason in report["regressions"]:
        print(f"  REGRESSION: {reason}", file=sys.stderr)

    print(f"\n{report['verdict']}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
