"""Run search quality eval against a live Metatron instance.

Usage:
    make eval                    # run and print results
    make eval-save               # run, print, and save to eval_results/
    make eval-compare            # run and compare with latest saved result
    make eval-history            # list all saved results

    python scripts/run_eval.py --workspace MTRNIX
    python scripts/run_eval.py --save
    python scripts/run_eval.py --compare
    python scripts/run_eval.py --compare eval_results/2026-03-25T14:30:00.json
    python scripts/run_eval.py --history
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

# Ensure src/ is importable when running as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Stub benchmark_qed if not installed (optional dependency) so that
# importing the metrics package doesn't blow up.
if "benchmark_qed" not in sys.modules:
    _mock = MagicMock()
    for _name in [
        "benchmark_qed",
        "benchmark_qed.autoe",
        "benchmark_qed.autoe.assertion_scores",
        "benchmark_qed.autod",
        "benchmark_qed.autod.data_model",
        "benchmark_qed.autod.data_model.text_unit",
        "benchmark_qed.autod.data_processor",
        "benchmark_qed.autod.data_processor.embedding",
        "benchmark_qed.autod.sampler",
        "benchmark_qed.autod.sampler.clustering",
        "benchmark_qed.autod.sampler.clustering.kmeans",
        "benchmark_qed.autoq",
        "benchmark_qed.autoq.data_model",
        "benchmark_qed.autoq.data_model.question",
        "benchmark_qed.autoq.question_gen",
        "benchmark_qed.autoq.question_gen.data_questions",
        "benchmark_qed.autoq.question_gen.data_questions.global_question_gen",
        "benchmark_qed.autoq.question_gen.data_questions.local_question_gen",
        "benchmark_qed.autoq.question_generator",
        "benchmark_qed.config",
        "benchmark_qed.config.llm_config",
        "benchmark_qed.llm",
        "benchmark_qed.llm.provider",
        "benchmark_qed.llm.provider.openai",
    ]:
        sys.modules[_name] = _mock

from metatron.benchmarker.services.eval_loader import (
    DEFAULT_TESTSET_PATH,
    load_eval_testset_from_path,
)
from metatron.benchmarker.services.metrics.retrieval import RetrievalMetrics
from metatron.retrieval.search import hybrid_search_and_answer

RESULTS_DIR = Path(__file__).parent.parent / "eval_results"


# ---------------------------------------------------------------------------
# Run eval
# ---------------------------------------------------------------------------

def run_eval(
    workspace: str, k: int, testset_path: Path,
) -> dict:
    """Run eval and return structured results."""
    ts = load_eval_testset_from_path(testset_path)
    rm = RetrievalMetrics()

    print(f"Workspace: {workspace}  |  K={k}  |  Queries: {len(ts.queries)}")
    print("-" * 70)

    per_query: list[dict] = []
    pairs: list[tuple[list[str], set[str]]] = []

    for q in ts.queries:
        trace = hybrid_search_and_answer(
            q.text, workspace, k, None, None, return_trace=True,
        )
        retrieved = (
            trace.get("retrieved_doc_labels", [])
            if isinstance(trace, dict)
            else []
        )
        result = rm.compute(retrieved, q.expected_doc_labels, k=k)
        pairs.append((retrieved, q.expected_doc_labels))
        per_query.append({
            "id": q.id,
            "text": q.text,
            "category": q.category,
            "precision_at_k": result["precision_at_k"],
            "mrr": result["mrr"],
            "ndcg_at_k": result["ndcg_at_k"],
            "retrieved": retrieved,
            "expected": sorted(q.expected_doc_labels),
        })
        print(
            f"[{q.id:<8}] "
            f"P@{k}={result['precision_at_k']:.2f}  "
            f"MRR={result['mrr']:.2f}  "
            f"NDCG@{k}={result['ndcg_at_k']:.2f}"
        )

    print("-" * 70)
    avgs = rm.compute_averages(pairs, k=k)
    print(
        f"OVERALL:   "
        f"P@{k}={avgs['avg_precision_at_k']:.4f}  "
        f"MRR={avgs['avg_mrr']:.4f}  "
        f"NDCG@{k}={avgs['avg_ndcg_at_k']:.4f}"
    )

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "workspace": workspace,
        "k": k,
        "averages": {
            "precision_at_k": avgs["avg_precision_at_k"],
            "mrr": avgs["avg_mrr"],
            "ndcg_at_k": avgs["avg_ndcg_at_k"],
        },
        "per_query": per_query,
    }


# ---------------------------------------------------------------------------
# Save / load results
# ---------------------------------------------------------------------------

def save_results(data: dict) -> Path:
    """Save results to eval_results/ as JSON."""
    RESULTS_DIR.mkdir(exist_ok=True)
    ts = data["timestamp"].replace(":", "-").replace("+", "_")
    path = RESULTS_DIR / f"{ts}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved to {path}")
    return path


def load_latest() -> dict | None:
    """Load the most recent saved result."""
    if not RESULTS_DIR.exists():
        return None
    files = sorted(RESULTS_DIR.glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def load_result(path: str) -> dict:
    """Load a specific result file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

def _delta_str(before: float, after: float) -> str:
    """Format delta with arrow indicator."""
    diff = after - before
    if abs(diff) < 0.0001:
        return "  0.0000   "
    sign = "+" if diff > 0 else ""
    # For these metrics, higher is better
    icon = " +" if diff > 0 else " !"
    return f"{sign}{diff:.4f} {icon}"


def compare_results(before: dict, after: dict) -> None:
    """Print side-by-side comparison of two eval runs."""
    print()
    print(f"BEFORE: {before['timestamp']}")
    print(f"NOW:    {after['timestamp']}")
    print()

    # Overall averages
    metrics = ["precision_at_k", "mrr", "ndcg_at_k"]
    labels = {"precision_at_k": "P@K", "mrr": "MRR", "ndcg_at_k": "NDCG@K"}

    print(f"{'Metric':<12} {'BEFORE':>10} {'NOW':>10} {'DELTA':>16}")
    print("-" * 50)
    for m in metrics:
        b = before["averages"][m]
        a = after["averages"][m]
        delta = _delta_str(b, a)
        print(f"{labels[m]:<12} {b:>10.4f} {a:>10.4f} {delta:>16}")

    # Per-query regressions and improvements
    before_by_id = {q["id"]: q for q in before["per_query"]}
    after_by_id = {q["id"]: q for q in after["per_query"]}

    regressions: list[str] = []
    improvements: list[str] = []

    for qid in after_by_id:
        if qid not in before_by_id:
            continue
        bq = before_by_id[qid]
        aq = after_by_id[qid]
        for m in metrics:
            diff = aq[m] - bq[m]
            if diff < -0.01:
                regressions.append(
                    f"  [{qid:<8}] {labels[m]}  {bq[m]:.2f} -> {aq[m]:.2f}"
                )
            elif diff > 0.01:
                improvements.append(
                    f"  [{qid:<8}] {labels[m]}  {bq[m]:.2f} -> {aq[m]:.2f}"
                )

    if regressions:
        print(f"\nRegressions ({len(regressions)}):")
        for r in regressions:
            print(r)

    if improvements:
        print(f"\nImprovements ({len(improvements)}):")
        for imp in improvements:
            print(imp)

    if not regressions and not improvements:
        print("\nNo significant per-query changes (threshold: 0.01)")


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def show_history() -> None:
    """List all saved eval results."""
    if not RESULTS_DIR.exists():
        print("No saved results. Run: make eval-save")
        return
    files = sorted(RESULTS_DIR.glob("*.json"))
    if not files:
        print("No saved results. Run: make eval-save")
        return

    print(f"{'#':<4} {'Timestamp':<28} {'P@K':>8} {'MRR':>8} {'NDCG@K':>8}")
    print("-" * 60)
    for i, f in enumerate(files, 1):
        data = json.loads(f.read_text(encoding="utf-8"))
        avgs = data["averages"]
        print(
            f"{i:<4} {data['timestamp']:<28} "
            f"{avgs['precision_at_k']:>8.4f} "
            f"{avgs['mrr']:>8.4f} "
            f"{avgs['ndcg_at_k']:>8.4f}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Search quality eval")
    parser.add_argument(
        "--workspace", "-w",
        default=os.environ.get("METATRON_EVAL_WORKSPACE", "MTRNIX"),
        help="Workspace ID (default: $METATRON_EVAL_WORKSPACE or MTRNIX)",
    )
    parser.add_argument(
        "--k", type=int, default=10,
        help="Top-K for metrics (default: 10)",
    )
    parser.add_argument(
        "--testset", type=str, default=None,
        help="Path to custom YAML test set (default: built-in)",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save results to eval_results/",
    )
    parser.add_argument(
        "--compare", nargs="?", const="latest", default=None,
        help="Run eval and compare with saved result (default: latest)",
    )
    parser.add_argument(
        "--history", action="store_true",
        help="List all saved eval results",
    )
    args = parser.parse_args()

    # History mode — no eval needed
    if args.history:
        show_history()
        return

    # Run eval
    testset_path = Path(args.testset) if args.testset else DEFAULT_TESTSET_PATH
    results = run_eval(args.workspace, args.k, testset_path)

    # Save if requested
    if args.save:
        save_results(results)

    # Compare if requested
    if args.compare is not None:
        if args.compare == "latest":
            before = load_latest()
            if before is None:
                print("\nNo saved results to compare with. Run: make eval-save")
                return
        else:
            before = load_result(args.compare)
        compare_results(before, results)

        # Auto-save current run when comparing
        if not args.save:
            save_results(results)


if __name__ == "__main__":
    main()
