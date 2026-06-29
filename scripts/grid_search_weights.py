#!/usr/bin/env python3
"""Two-phase grid search for optimal scoring weights per query profile.

Phase 1 (--cache): Run the full retrieval pipeline (recall + rerank) once per
eval query and cache raw signals to disk. This is the expensive step.

Phase 2 (--search, default): Load cached signals, iterate weight combinations
offline. Recomputes signal scores, pool selection, rerank normalization, and
final blended scores — no live services needed.

Usage:
    # Phase 1: generate cache (requires live services)
    python scripts/grid_search_weights.py --cache --workspace MTRNIX

    # Phase 2: search weights (fast, offline)
    python scripts/grid_search_weights.py --workspace MTRNIX --step 0.10

    # Both phases in one run
    python scripts/grid_search_weights.py --cache --search --workspace MTRNIX

    # Reuse a specific cache file
    python scripts/grid_search_weights.py --cache-file eval_results/grid_cache_*.json --step 0.05

    # Single profile, fine step
    python scripts/grid_search_weights.py --profile execution --step 0.05
"""

from __future__ import annotations

import argparse
import glob as globmod
import itertools
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import structlog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Stub benchmark_qed (same as run_eval.py)
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

from metronix.benchmarker.services.eval_loader import (
    DEFAULT_TESTSET_PATH,
    load_eval_testset_from_path,
)
from metronix.benchmarker.services.metrics.retrieval import RetrievalMetrics
from metronix.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS
from metronix.retrieval.scoring import (
    compute_final_score,
    compute_signal_score,
    source_balance,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Weight grid generation
# ---------------------------------------------------------------------------


def _weight_grid(step: float = 0.05) -> list[dict[str, float]]:
    """Generate weight combinations that sum to ~0.85 (excluding blend)."""
    values = [round(v, 2) for v in [i * step for i in range(int(0.5 / step) + 1)]]
    combos = []
    for dense, graph, metadata, recency, balance in itertools.product(
        values,
        values,
        values,
        values,
        [0.05],
    ):
        total = dense + graph + metadata + recency + balance
        if 0.80 <= total <= 0.90:
            combos.append(
                {
                    "dense_weight": dense,
                    "graph_weight": graph,
                    "metadata_weight": metadata,
                    "recency_weight": recency,
                    "balance_weight": balance,
                }
            )
    return combos


def _blend_grid(step: float = 0.05) -> list[float]:
    """Generate blend_weight values."""
    return [round(v, 2) for v in [i * step for i in range(1, 10)]]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Phase 1: Cache generation
# ---------------------------------------------------------------------------


def _result_type(r: dict) -> str:
    """Extract source type from a search result dict."""
    return (
        r.get("type")
        or (r.get("payload") or {}).get("type")
        or (r.get("metadata") or {}).get("type")
        or "unknown"
    ).lower()


def generate_cache(
    workspace: str,
    testset_path: Path,
    rerank_cache_size: int = 50,
) -> dict:
    """Run the retrieval pipeline for each eval query and cache raw signals.

    Returns a dict keyed by query ID with per-candidate signal data.
    """
    from metronix.core.config import Settings
    from metronix.retrieval.channels import merge_channels
    from metronix.retrieval.reranker import rerank
    from metronix.retrieval.scoring import recency_score as calc_recency
    from metronix.retrieval.search import (
        _build_recall_context,
        _run_recall_channels,
        classify_query,
        detect_response_language,
        expand_query,
        resolve_query,
        translate_query_to_english,
    )

    settings = Settings()
    ts = load_eval_testset_from_path(testset_path)
    queries = [q for q in ts.queries if q.stable and q.expected_doc_labels]

    cache: dict = {
        "meta": {
            "workspace": workspace,
            "timestamp": datetime.now(UTC).isoformat(),
            "rerank_cache_size": rerank_cache_size,
            "query_count": len(queries),
        },
        "queries": {},
    }

    for idx, q in enumerate(queries):
        t0 = time.time()
        logger.info("cache.query_start", idx=idx + 1, total=len(queries), qid=q.id)

        # -- Query preprocessing (same as hybrid_search_and_answer) --
        rq = resolve_query(q.text.strip())
        lang = detect_response_language(rq)
        eq = expand_query(rq)
        sq = translate_query_to_english(eq) if any("\u0400" <= c <= "\u04ff" for c in eq) else eq

        # Classify
        if settings.query_classifier_enabled:
            if any("\u0400" <= c <= "\u04ff" for c in rq):
                trans_for_cls = sq if rq == eq else translate_query_to_english(rq)
            else:
                trans_for_cls = rq
            classification = classify_query(rq, translated_query=trans_for_cls)
        else:
            classification = {
                "profile": "mixed",
                "confidence": 1.0,
                "method": "disabled",
            }

        # Build recall context
        recall_ctx = _build_recall_context(
            original_query=rq,
            translated_query=sq,
            expanded_query=eq,
            detected_language=lang,
            workspace_id=workspace,
            access_filter=None,
            settings=settings,
        )

        # Run recall channels
        dense_r, exact_r, metadata_r, graph_r = _run_recall_channels(recall_ctx)
        merged = merge_channels([dense_r, exact_r, metadata_r, graph_r])

        # Compute recency + balance for each candidate
        type_cache: dict[str, str] = {}
        for mr in merged:
            type_cache[mr["chunk_id"]] = _result_type(mr["memory"])

        type_counts = dict(Counter(type_cache.values()))
        total_merged = len(merged)

        candidates_for_rerank = []
        candidate_signals: list[dict] = []

        for mr in merged:
            mem = mr["memory"]
            date_str = mem.get("date") or (mem.get("payload") or {}).get("date")
            rec = 1.0
            if date_str:
                try:
                    dt = datetime.fromisoformat(str(date_str))
                    rec = calc_recency(dt)
                except (ValueError, TypeError):
                    rec = 1.0

            bal = source_balance(
                type_cache[mr["chunk_id"]],
                type_counts,
                total_merged,
            )
            doc_label = (
                mr.get("doc_label")
                or mr["memory"].get("doc_label")
                or (mr["memory"].get("payload") or {}).get("doc_label")
                or ""
            )
            source_type = type_cache[mr["chunk_id"]]

            candidate_signals.append(
                {
                    "chunk_id": mr["chunk_id"],
                    "doc_label": doc_label,
                    "source_type": source_type,
                    "channel_scores": mr["channel_scores"],
                    "recency": rec,
                    "balance": bal,
                    "rerank_score_raw": None,  # filled after rerank
                }
            )
            candidates_for_rerank.append(mr["memory"])

        # Rerank a larger pool
        pool = candidates_for_rerank[:rerank_cache_size]
        reranked = rerank(query=rq, results=pool, top_k=len(pool))

        # Map rerank scores back to candidate signals
        rerank_by_id: dict[str, float] = {}
        for r in reranked:
            rid = str(r.get("id", ""))
            rerank_by_id[rid] = float(r.get("rerank_score", 0.0))

        for cs in candidate_signals[:rerank_cache_size]:
            cs["rerank_score_raw"] = rerank_by_id.get(cs["chunk_id"], 0.0)

        # Drop candidates beyond rerank pool (no rerank score available)
        candidate_signals = candidate_signals[:rerank_cache_size]

        elapsed = time.time() - t0
        logger.info(
            "cache.query_done",
            qid=q.id,
            candidates=len(candidate_signals),
            elapsed_s=round(elapsed, 2),
        )

        cache["queries"][q.id] = {
            "text": q.text,
            "expected_doc_labels": list(q.expected_doc_labels),
            "category": q.category,
            "profile": classification["profile"],
            "candidates": candidate_signals,
        }

    return cache


def save_cache(cache: dict, workspace: str) -> Path:
    """Save cache to eval_results/grid/ and return the file path."""
    out_dir = Path(__file__).parent.parent / "eval_results" / "grid"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
    out_file = out_dir / f"grid_cache_{workspace}_{ts}.json"
    out_file.write_text(json.dumps(cache, indent=2, default=str))
    return out_file


def load_cache(path: str) -> dict:
    """Load cache from a JSON file, supporting glob patterns."""
    matches = sorted(globmod.glob(path))
    if not matches:
        raise FileNotFoundError(f"No cache file matching: {path}")
    # Use the most recent match
    chosen = matches[-1]
    logger.info("cache.loading", path=chosen)
    return json.loads(Path(chosen).read_text())


# ---------------------------------------------------------------------------
# Phase 2: Offline weight search from cache
# ---------------------------------------------------------------------------


def search_from_cache(
    cache: dict,
    step: float = 0.10,
    profile_filter: str | None = None,
    metric: str = "combined",
    top: int = 3,
    k: int = 10,
    pool_size: int = 35,
) -> dict[str, dict]:
    """Iterate weight combinations using cached signals.

    Returns best_per_profile: {profile: {weights, metrics, score}}.
    """
    weight_combos = _weight_grid(step=step)
    blend_values = _blend_grid(step=step)

    profiles = [profile_filter] if profile_filter else list(QUERY_PROFILE_WEIGHTS.keys())

    # Group queries by profile
    queries_by_profile: dict[str, list[dict]] = {}
    for qid, qdata in cache["queries"].items():
        p = qdata.get("profile", "mixed")
        queries_by_profile.setdefault(p, []).append({**qdata, "id": qid})

    print(f"Grid: {len(weight_combos)} signal combos x {len(blend_values)} blend values")
    print(f"Profiles: {profiles}")
    print(f"Optimizing: {metric}")
    print()

    rm = RetrievalMetrics()
    best_per_profile: dict[str, dict] = {}

    for profile in profiles:
        print(f"\n{'=' * 60}")
        print(f"Profile: {profile}")
        print(f"{'=' * 60}")

        # Use profile queries if available, fallback to all queries
        profile_queries = queries_by_profile.get(profile, [])
        if not profile_queries:
            all_queries = [{**qd, "id": qid} for qid, qd in cache["queries"].items()]
            profile_queries = all_queries

        if not profile_queries:
            print("  No queries for this profile, skipping")
            continue

        results: list[dict] = []
        total_combos = len(weight_combos) * len(blend_values)

        for i, (weights, blend) in enumerate(
            itertools.product(weight_combos, blend_values),
        ):
            full_weights = {**weights, "blend_weight": blend}
            scoring_weights = {k_: v for k_, v in full_weights.items() if k_ != "blend_weight"}

            # Evaluate this weight combo across all profile queries
            totals = {"precision_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0}
            for qdata in profile_queries:
                candidates = qdata["candidates"]
                expected = set(qdata["expected_doc_labels"])

                # Recompute signal scores with new weights
                scored = []
                for c in candidates:
                    sig = compute_signal_score(
                        channel_scores=c["channel_scores"],
                        recency=c["recency"],
                        balance=c["balance"],
                        **scoring_weights,
                    )
                    scored.append({**c, "signal_score": sig})

                # Sort by signal score, take top pool_size
                scored.sort(key=lambda x: x["signal_score"], reverse=True)
                pool = scored[:pool_size]

                # Normalize rerank scores within pool
                raw_reranks = [c.get("rerank_score_raw", 0.0) or 0.0 for c in pool]
                if raw_reranks:
                    min_r = min(raw_reranks)
                    max_r = max(raw_reranks)
                    spread = max_r - min_r
                else:
                    spread = 0.0

                for idx_c, c in enumerate(pool):
                    raw = raw_reranks[idx_c]
                    norm_rerank = 1.0 if spread == 0 else (raw - min_r) / spread

                    c["final_score"] = compute_final_score(
                        signal_score=c["signal_score"],
                        rerank_score=norm_rerank,
                        blend_weight=blend,
                    )

                # Sort by final score, extract doc labels
                pool.sort(key=lambda x: x["final_score"], reverse=True)
                retrieved = []
                seen_labels: set[str] = set()
                for c in pool:
                    dl = c.get("doc_label", "")
                    if dl and dl not in seen_labels:
                        seen_labels.add(dl)
                        retrieved.append(dl)

                result = rm.compute(retrieved, expected, k=k)
                for key in totals:
                    totals[key] += result[key]

            n = len(profile_queries)
            avg_metrics = {k_: v / n for k_, v in totals.items()} if n > 0 else totals
            score = _compute_objective(avg_metrics, metric)
            results.append(
                {
                    "weights": full_weights,
                    "metrics": avg_metrics,
                    "score": score,
                }
            )

            if (i + 1) % 100 == 0:
                best_so_far = max(r["score"] for r in results)
                print(f"  [{i + 1}/{total_combos}] best so far: {best_so_far:.4f}")

        results.sort(key=lambda x: x["score"], reverse=True)
        best_per_profile[profile] = results[0]

        print(f"\nTop {top} for {profile}:")
        for j, r in enumerate(results[:top]):
            w = r["weights"]
            m = r["metrics"]
            print(
                f"  #{j + 1}: score={r['score']:.4f} "
                f"P@{k}={m.get('precision_at_k', 0):.4f} "
                f"MRR={m.get('mrr', 0):.4f} "
                f"NDCG={m.get('ndcg_at_k', 0):.4f}"
            )
            print(f"       weights: {json.dumps(w)}")

    return best_per_profile


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Two-phase grid search for scoring weights",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="Phase 1: run retrieval pipeline and cache signals",
    )
    parser.add_argument(
        "--search",
        action="store_true",
        help="Phase 2: iterate weight combos from cache (default if no --cache)",
    )
    parser.add_argument(
        "--cache-file",
        default=None,
        help="Path/glob to existing cache file for Phase 2",
    )
    parser.add_argument(
        "--rerank-cache-size",
        type=int,
        default=50,
        help="Number of candidates to rerank per query in Phase 1 (default 50)",
    )
    parser.add_argument("--profile", default=None, help="Single profile to search")
    parser.add_argument(
        "--metric",
        default="combined",
        choices=["mrr", "ndcg", "precision", "combined"],
        help="Metric to optimize",
    )
    parser.add_argument("--top", type=int, default=3, help="Show top N results")
    parser.add_argument(
        "--step",
        type=float,
        default=0.10,
        help="Weight grid step size (default 0.10)",
    )
    parser.add_argument("--workspace", default="MTRNIX")
    parser.add_argument("--k", type=int, default=10, help="K for P@K, NDCG@K")
    args = parser.parse_args()

    do_cache = args.cache
    do_search = args.search

    # Default: if neither flag set, do search only
    if not do_cache and not do_search:
        do_search = True

    cache_data: dict | None = None
    cache_file_path: Path | None = None

    # Phase 1: cache generation
    if do_cache:
        print("=" * 60)
        print("PHASE 1: Cache generation")
        print("=" * 60)
        t0 = time.time()
        cache_data = generate_cache(
            workspace=args.workspace,
            testset_path=DEFAULT_TESTSET_PATH,
            rerank_cache_size=args.rerank_cache_size,
        )
        cache_file_path = save_cache(cache_data, args.workspace)
        elapsed = time.time() - t0
        n_queries = len(cache_data["queries"])
        print(f"\nCache saved: {cache_file_path}")
        print(f"Queries: {n_queries}, Time: {elapsed:.1f}s")

    # Phase 2: weight search
    if do_search:
        if cache_data is None:
            if args.cache_file:
                cache_data = load_cache(args.cache_file)
            else:
                # Find most recent cache file for this workspace
                pattern = str(
                    Path(__file__).parent.parent
                    / "eval_results"
                    / "grid"
                    / f"grid_cache_{args.workspace}_*.json"
                )
                cache_data = load_cache(pattern)

        print("\n" + "=" * 60)
        print("PHASE 2: Weight search")
        print("=" * 60)

        t0 = time.time()
        best_per_profile = search_from_cache(
            cache=cache_data,
            step=args.step,
            profile_filter=args.profile,
            metric=args.metric,
            top=args.top,
            k=args.k,
        )
        elapsed = time.time() - t0

        # Save results
        out_dir = Path(__file__).parent.parent / "eval_results" / "grid"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        out_file = out_dir / f"grid_search_{ts}.json"
        out_file.write_text(
            json.dumps(best_per_profile, indent=2, default=str),
        )

        # Summary
        print(f"\n{'=' * 60}")
        print("RECOMMENDED WEIGHTS")
        print(f"{'=' * 60}")
        for profile, best in best_per_profile.items():
            print(f"\n{profile}:")
            print(f"  {json.dumps(best['weights'], indent=4)}")
        print(f"\nSearch time: {elapsed:.1f}s")
        print(f"Results saved to {out_file}")


if __name__ == "__main__":
    main()
