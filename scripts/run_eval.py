"""Run search quality eval against a live Metronix instance.

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
import asyncio
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

from uuid import uuid4

from metronix.benchmarker.services.eval_loader import (
    DEFAULT_TESTSET_PATH,
    load_eval_testset_from_path,
)
from metronix.benchmarker.services.metrics.retrieval import RetrievalMetrics
from metronix.llm.telemetry import set_telemetry_context
from metronix.retrieval.search import hybrid_search_and_answer
from metronix.storage.qdrant import clear_store_cache

RESULTS_DIR = Path(__file__).parent.parent / "eval_results"


# ---------------------------------------------------------------------------
# Run eval
# ---------------------------------------------------------------------------


async def run_eval(
    workspace: str,
    k: int,
    testset_path: Path,
    *,
    include_unstable: bool = False,
) -> dict:
    """Run eval and return structured results.

    Runs every query inside a single event loop so the async Qdrant client
    cached in ``_async_hybrid_stores`` stays bound to the loop for the full
    run. This fixes the ``qdrant.async.hybrid_search.fallback`` flake where
    previous per-query ``asyncio.run()`` calls left a client parked on a
    closed loop.
    """
    ts = load_eval_testset_from_path(testset_path)
    rm = RetrievalMetrics()

    queries = ts.queries if include_unstable else [q for q in ts.queries if q.stable]
    skipped = len(ts.queries) - len(queries)

    positive_queries = [q for q in queries if q.expected_doc_labels]
    negative_queries = [q for q in queries if not q.expected_doc_labels]

    header = (
        f"Workspace: {workspace}  |  K={k}  |  "
        f"Queries: {len(queries)} "
        f"({len(positive_queries)} positive, {len(negative_queries)} negative)"
    )
    if skipped:
        header += f"  |  Skipped: {skipped} unstable (use --all to include)"
    print(header)
    print("-" * 70)

    per_query: list[dict] = []
    pairs: list[tuple[list[str], set[str]]] = []

    # --- Positive queries: expect relevant docs ---
    if positive_queries:
        print("POSITIVE (should find relevant docs):")
    for q in positive_queries:
        with set_telemetry_context(
            workspace_id=workspace,
            source="eval",
            correlation_id=uuid4(),
        ):
            trace = await hybrid_search_and_answer(
                query=q.text,
                user_id=workspace,
                k=k,
                workspace_id=None,
                intent_query=None,
                return_trace=True,
            )
        retrieved = trace.get("retrieved_doc_labels", []) if isinstance(trace, dict) else []
        retrieved = list(dict.fromkeys(retrieved))  # deduplicate preserving order
        result = rm.compute(retrieved, q.expected_doc_labels, k=k)
        pairs.append((retrieved, q.expected_doc_labels))
        per_query.append(
            {
                "id": q.id,
                "text": q.text,
                "category": q.category,
                "is_negative": False,
                "precision_at_k": result["precision_at_k"],
                "mrr": result["mrr"],
                "ndcg_at_k": result["ndcg_at_k"],
                "retrieved": retrieved,
                "expected": sorted(q.expected_doc_labels),
            }
        )
        print(
            f"  [{q.id:<8}] "
            f"P@{k}={result['precision_at_k']:.2f}  "
            f"MRR={result['mrr']:.2f}  "
            f"NDCG@{k}={result['ndcg_at_k']:.2f}"
        )

    # --- Negative queries: expect NO relevant docs ---
    neg_correct = 0
    if negative_queries:
        print("\nNEGATIVE (should NOT find relevant docs):")
    for q in negative_queries:
        with set_telemetry_context(
            workspace_id=workspace,
            source="eval",
            correlation_id=uuid4(),
        ):
            trace = await hybrid_search_and_answer(
                query=q.text,
                user_id=workspace,
                k=k,
                workspace_id=None,
                intent_query=None,
                return_trace=True,
            )
        retrieved = trace.get("retrieved_doc_labels", []) if isinstance(trace, dict) else []
        retrieved = list(dict.fromkeys(retrieved))  # deduplicate preserving order
        n_retrieved = len(retrieved)
        # For negative queries: success = no docs retrieved (or very few)
        is_correct = n_retrieved == 0
        if is_correct:
            neg_correct += 1
        status = "OK" if is_correct else f"NOISE ({n_retrieved} docs)"
        per_query.append(
            {
                "id": q.id,
                "text": q.text,
                "category": q.category,
                "is_negative": True,
                "retrieved_count": n_retrieved,
                "is_correct": is_correct,
                "retrieved": retrieved,
                "expected": [],
            }
        )
        print(f"  [{q.id:<8}] {status}")

    # --- Summary ---
    print("-" * 70)

    if positive_queries:
        avgs = rm.compute_averages(pairs, k=k)
        print(
            f"POSITIVE:  "
            f"P@{k}={avgs['avg_precision_at_k']:.4f}  "
            f"MRR={avgs['avg_mrr']:.4f}  "
            f"NDCG@{k}={avgs['avg_ndcg_at_k']:.4f}  "
            f"({len(positive_queries)} queries)"
        )
    else:
        avgs = {"avg_precision_at_k": 0.0, "avg_mrr": 0.0, "avg_ndcg_at_k": 0.0}

    if negative_queries:
        neg_accuracy = neg_correct / len(negative_queries)
        print(
            f"NEGATIVE:  "
            f"accuracy={neg_accuracy:.2f}  "
            f"({neg_correct}/{len(negative_queries)} correctly empty)"
        )
    else:
        neg_accuracy = None

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "workspace": workspace,
        "k": k,
        "averages": {
            "precision_at_k": avgs["avg_precision_at_k"],
            "mrr": avgs["avg_mrr"],
            "ndcg_at_k": avgs["avg_ndcg_at_k"],
            "negative_accuracy": neg_accuracy,
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

    # Overall averages (positive metrics)
    metrics = ["precision_at_k", "mrr", "ndcg_at_k"]
    labels = {
        "precision_at_k": "P@K",
        "mrr": "MRR",
        "ndcg_at_k": "NDCG@K",
        "negative_accuracy": "Neg Acc",
    }

    print(f"{'Metric':<12} {'BEFORE':>10} {'NOW':>10} {'DELTA':>16}")
    print("-" * 50)
    for m in metrics:
        b = before["averages"][m]
        a = after["averages"][m]
        delta = _delta_str(b, a)
        print(f"{labels[m]:<12} {b:>10.4f} {a:>10.4f} {delta:>16}")

    # Negative accuracy (may be absent in older results)
    b_neg = before["averages"].get("negative_accuracy")
    a_neg = after["averages"].get("negative_accuracy")
    if a_neg is not None:
        b_val = b_neg if b_neg is not None else 0.0
        delta = _delta_str(b_val, a_neg)
        b_str = f"{b_val:>10.4f}" if b_neg is not None else f"{'N/A':>10}"
        print(f"{labels['negative_accuracy']:<12} {b_str} {a_neg:>10.4f} {delta:>16}")

    # Per-query regressions and improvements (positive queries only)
    before_by_id = {q["id"]: q for q in before["per_query"]}
    after_by_id = {q["id"]: q for q in after["per_query"]}

    regressions: list[str] = []
    improvements: list[str] = []

    for qid, aq in after_by_id.items():
        if qid not in before_by_id:
            continue
        bq = before_by_id[qid]

        # Negative queries: compare is_correct
        if aq.get("is_negative"):
            b_ok = bq.get("is_correct", True)
            a_ok = aq.get("is_correct", True)
            if b_ok and not a_ok:
                regressions.append(
                    f"  [{qid:<8}] was clean, now returns {aq.get('retrieved_count', '?')} docs"
                )
            elif not b_ok and a_ok:
                improvements.append(f"  [{qid:<8}] was noisy, now clean")
            continue

        # Positive queries: compare metrics
        for m in metrics:
            bv = bq.get(m, 0.0)
            av = aq.get(m, 0.0)
            diff = av - bv
            if diff < -0.01:
                regressions.append(f"  [{qid:<8}] {labels[m]}  {bv:.2f} -> {av:.2f}")
            elif diff > 0.01:
                improvements.append(f"  [{qid:<8}] {labels[m]}  {bv:.2f} -> {av:.2f}")

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

    print(f"{'#':<4} {'Timestamp':<28} {'P@K':>8} {'MRR':>8} {'NDCG@K':>8} {'Neg':>8}")
    print("-" * 70)
    for i, f in enumerate(files, 1):
        data = json.loads(f.read_text(encoding="utf-8"))
        avgs = data["averages"]
        neg = avgs.get("negative_accuracy")
        neg_str = f"{neg:>8.2f}" if neg is not None else f"{'N/A':>8}"
        print(
            f"{i:<4} {data['timestamp']:<28} "
            f"{avgs['precision_at_k']:>8.4f} "
            f"{avgs['mrr']:>8.4f} "
            f"{avgs['ndcg_at_k']:>8.4f} "
            f"{neg_str}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Search quality eval")
    parser.add_argument(
        "--workspace",
        "-w",
        default=os.environ.get("METRONIX_EVAL_WORKSPACE", "MTRNIX"),
        help="Workspace ID (default: $METRONIX_EVAL_WORKSPACE or MTRNIX)",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="Top-K for metrics (default: 10)",
    )
    parser.add_argument(
        "--testset",
        type=str,
        default=None,
        help="Path to custom YAML test set (default: built-in)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to eval_results/",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write result JSON to this path",
    )
    parser.add_argument(
        "--compare",
        nargs="?",
        const="latest",
        default=None,
        help="Run eval and compare with saved result (default: latest)",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="List all saved eval results",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include unstable queries (test data that may not survive reindex)",
    )
    args = parser.parse_args()

    # History mode — no eval needed
    if args.history:
        show_history()
        return

    # Run eval
    testset_path = Path(args.testset) if args.testset else DEFAULT_TESTSET_PATH
    # Flush any stray async Qdrant client an import-time side effect may have
    # parked on a different loop — we want the cache to bind to the single
    # loop that asyncio.run() below is about to create.
    clear_store_cache()
    results = asyncio.run(
        run_eval(
            args.workspace,
            args.k,
            testset_path,
            include_unstable=args.all,
        )
    )

    # Save if requested
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    elif args.save:
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
