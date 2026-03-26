#!/usr/bin/env python3
"""Grid search for optimal scoring weights per query profile.

Systematically tests weight combinations using the eval test set
and reports best-performing weights by MRR + NDCG@10.

Usage:
    python scripts/grid_search_weights.py                      # search all profiles
    python scripts/grid_search_weights.py --profile execution   # search one profile
    python scripts/grid_search_weights.py --metric mrr          # optimize for MRR
    python scripts/grid_search_weights.py --top 5               # show top 5 results
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Stub benchmark_qed (same as run_eval.py)
if "benchmark_qed" not in sys.modules:
    _mock = MagicMock()
    for _name in [
        "benchmark_qed", "benchmark_qed.autoe",
        "benchmark_qed.autoe.assertion_scores",
        "benchmark_qed.autod", "benchmark_qed.autod.data_model",
        "benchmark_qed.autod.data_model.text_unit",
        "benchmark_qed.autod.data_processor",
        "benchmark_qed.autod.data_processor.embedding",
        "benchmark_qed.autod.sampler",
        "benchmark_qed.autod.sampler.clustering",
        "benchmark_qed.autod.sampler.clustering.kmeans",
        "benchmark_qed.autoq", "benchmark_qed.autoq.data_model",
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
from metatron.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS
from metatron.retrieval.search import hybrid_search_and_answer


def _weight_grid(step: float = 0.05) -> list[dict[str, float]]:
    """Generate weight combinations that sum to ~0.85 (excluding blend)."""
    values = [round(v, 2) for v in [i * step for i in range(int(0.5 / step) + 1)]]
    combos = []
    for dense, graph, metadata, recency, balance in itertools.product(
        values, values, values, values, [0.05],
    ):
        total = dense + graph + metadata + recency + balance
        if 0.80 <= total <= 0.90:
            combos.append({
                "dense_weight": dense,
                "graph_weight": graph,
                "metadata_weight": metadata,
                "recency_weight": recency,
                "balance_weight": balance,
            })
    return combos


def _blend_grid(step: float = 0.05) -> list[float]:
    """Generate blend_weight values."""
    return [round(v, 2) for v in [i * step for i in range(1, 10)]]


def _run_eval_for_profile(
    workspace: str, k: int, testset_path: Path, profile_filter: str | None,
) -> dict:
    """Run eval queries, optionally filtering by category matching profile."""
    ts = load_eval_testset_from_path(testset_path)
    queries = [q for q in ts.queries if q.stable and q.expected_doc_labels]
    if profile_filter:
        queries = [q for q in queries if q.category == profile_filter]
    if not queries:
        # Fallback: use all positive queries if no category match
        queries = [q for q in ts.queries if q.stable and q.expected_doc_labels]

    rm = RetrievalMetrics()
    totals = {"precision_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0}
    for q in queries:
        trace = hybrid_search_and_answer(
            q.text, workspace, k, None, None, return_trace=True,
        )
        retrieved = trace.get("retrieved_doc_labels", []) if isinstance(trace, dict) else []
        result = rm.compute(retrieved, q.expected_doc_labels, k=k)
        for key in totals:
            totals[key] += result[key]
    n = len(queries)
    return {k_: v / n for k_, v in totals.items()} if n > 0 else totals


def _compute_objective(metrics: dict, metric: str) -> float:
    if metric == "mrr":
        return metrics.get("mrr", 0)
    elif metric == "ndcg":
        return metrics.get("ndcg_at_k", 0)
    elif metric == "precision":
        return metrics.get("precision_at_k", 0)
    else:  # combined
        return (
            0.4 * metrics.get("mrr", 0)
            + 0.4 * metrics.get("ndcg_at_k", 0)
            + 0.2 * metrics.get("precision_at_k", 0)
        )


def main():
    parser = argparse.ArgumentParser(description="Grid search for scoring weights")
    parser.add_argument("--profile", default=None, help="Single profile to search")
    parser.add_argument("--metric", default="combined",
                        choices=["mrr", "ndcg", "precision", "combined"],
                        help="Metric to optimize")
    parser.add_argument("--top", type=int, default=3, help="Show top N results")
    parser.add_argument("--step", type=float, default=0.10,
                        help="Weight grid step size (default 0.10)")
    parser.add_argument("--workspace", default="MTRNIX")
    parser.add_argument("--k", type=int, default=10, help="K for P@K, NDCG@K")
    args = parser.parse_args()

    profiles = [args.profile] if args.profile else list(QUERY_PROFILE_WEIGHTS.keys())
    weight_combos = _weight_grid(step=args.step)
    blend_values = _blend_grid(step=args.step)

    print(f"Grid: {len(weight_combos)} signal combos × {len(blend_values)} blend values")
    print(f"Profiles: {profiles}")
    print(f"Optimizing: {args.metric}")
    print()

    best_per_profile: dict[str, dict] = {}

    for profile in profiles:
        print(f"\n{'='*60}")
        print(f"Profile: {profile}")
        print(f"{'='*60}")

        original_weights = QUERY_PROFILE_WEIGHTS.get(profile, {}).copy()
        results = []
        total = len(weight_combos) * len(blend_values)

        for i, (weights, blend) in enumerate(
            itertools.product(weight_combos, blend_values)
        ):
            full_weights = {**weights, "blend_weight": blend}
            QUERY_PROFILE_WEIGHTS[profile] = full_weights

            metrics = _run_eval_for_profile(
                args.workspace, args.k, DEFAULT_TESTSET_PATH, profile,
            )
            score = _compute_objective(metrics, args.metric)

            results.append({"weights": full_weights, "metrics": metrics, "score": score})

            if (i + 1) % 50 == 0:
                print(f"  [{i+1}/{total}] best so far: {max(r['score'] for r in results):.4f}")

        # Restore original weights
        QUERY_PROFILE_WEIGHTS[profile] = original_weights

        results.sort(key=lambda x: x["score"], reverse=True)
        best_per_profile[profile] = results[0]

        print(f"\nTop {args.top} for {profile}:")
        for j, r in enumerate(results[:args.top]):
            w = r["weights"]
            m = r["metrics"]
            print(f"  #{j+1}: score={r['score']:.4f} "
                  f"P@10={m.get('precision_at_k', 0):.4f} "
                  f"MRR={m.get('mrr', 0):.4f} "
                  f"NDCG={m.get('ndcg_at_k', 0):.4f}")
            print(f"       weights: {json.dumps(w)}")

    # Save results
    out_dir = Path(__file__).parent.parent / "eval_results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"grid_search_{datetime.now(UTC).strftime('%Y-%m-%dT%H-%M-%S')}.json"
    out_file.write_text(json.dumps(best_per_profile, indent=2, default=str))

    # Summary
    print(f"\n{'='*60}")
    print("RECOMMENDED WEIGHTS")
    print(f"{'='*60}")
    for profile, best in best_per_profile.items():
        print(f"\n{profile}:")
        print(f"  {json.dumps(best['weights'], indent=4)}")
    print(f"\nResults saved to {out_file}")


if __name__ == "__main__":
    main()
