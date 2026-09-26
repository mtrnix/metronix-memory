"""End-to-end retrieval probe: does the gold evidence reach the answer model's context?

Runs the production ``hybrid_search_and_answer`` (recall channels, merge, signal scoring,
cross-encoder rerank, fragment selection under the token budget) on a loaded MuSiQue
workspace and checks, per question, whether each gold paragraph is among the
``retrieved_doc_labels`` (post-rerank top-k) and among the ``fragments`` handed to the LLM.

Only LLM calls are removed, so the probe needs no chat model and measures retrieval alone:

* ``resolve_query`` and answer generation go through stubs (the resolver stub returns
  nothing, which makes ``resolve_query`` fall back to the original question);
* query expansion and the query classifier are switched off with their own settings
  (``QUERY_EXPANSION_ENABLED=false``, ``QUERY_CLASSIFIER_ENABLED=false``), so the dense
  query is the question itself and the scoring profile is ``mixed``.

The graph configuration is chosen per run with ``--graph`` and the score fusion with
``--fusion``; each run should be a fresh process because ``metronix.retrieval.search``
reads its settings at import time.

``--rerank-cache`` serves cross-encoder scores from a JSONL cache (the model is
deterministic, so results are identical to uncached runs). ``--trace`` adds, per gold
document, its rank at every stage: dense channel, graph channel, signal-score order,
cross-encoder order within the rerank pool, and the final top-k.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

GRAPH_MODES = {
    # graph recall channel removed (harness ablation, not a product setting)
    "off": {},
    # production default: BFS graph channel
    "bfs": {},
    "ppr": {"METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED": "true"},
    "ppr-novel": {
        "METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED": "true",
        "METRONIX_RETRIEVAL_GRAPH_PPR_EXCLUDE_DENSE_ANCHORS": "true",
    },
}

# Score-fusion strategies (METRONIX_RETRIEVAL_FUSION_MODE); "signal" is the production
# default (compute_signal_score blended with the cross-encoder).
FUSION_MODES = ("signal", "rrf", "calibrated", "bridge")

RETRIEVAL_ONLY_ENV = {
    "QUERY_EXPANSION_ENABLED": "false",
    "QUERY_CLASSIFIER_ENABLED": "false",
}

RECALL_KS = (2, 5, 10)


def gold_positions(gold: list[str], labels: list[str]) -> dict[str, int | None]:
    """1-based position of each gold doc among distinct labels (None if absent)."""
    order = list(dict.fromkeys(label for label in labels if label))
    return {g: (order.index(g) + 1 if g in order else None) for g in gold}


def score_row(manifest_row: dict, trace: dict) -> dict:
    gold = [h["doc_label"] for h in manifest_row["hops"]]
    retrieved = trace.get("retrieved_doc_labels") or []
    context = [f.get("doc_label", "") for f in trace.get("fragments") or []]
    stages = trace.get("pipeline_stages") or {}
    ctx_pos = gold_positions(gold, context)
    return {
        "qid": manifest_row["qid"],
        "gold": gold,
        "retrieved_rank": gold_positions(gold, retrieved),
        "context_rank": ctx_pos,
        "context_hop0": ctx_pos[gold[0]] is not None,
        "context_last_hop": ctx_pos[gold[-1]] is not None,
        "context_both": all(v is not None for v in ctx_pos.values()),
        "context_docs": len(dict.fromkeys(context)),
        "recall_graph_count": stages.get("recall_graph_count"),
        "recall_total_unique": stages.get("recall_total_unique"),
    }


def _within(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def aggregate(rows: list[dict]) -> dict:
    n = len(rows)
    out = {"questions": n}
    for key in ("context_hop0", "context_last_hop", "context_both"):
        out[key] = sum(r[key] for r in rows)
    for k in (5, 10):
        out[f"retrieved@{k}_both"] = sum(
            all(_within(v, k) for v in r["retrieved_rank"].values()) for r in rows
        )
        out[f"retrieved@{k}_last_hop"] = sum(
            _within(list(r["retrieved_rank"].values())[-1], k) for r in rows
        )
    for k in RECALL_KS:
        # Passage recall@k as in HippoRAG / HippoRAG 2: share of a question's supporting
        # paragraphs in the top k, averaged over questions (percent).
        out[f"recall@{k}"] = (
            round(
                100.0
                * sum(
                    sum(_within(v, k) for v in r["retrieved_rank"].values())
                    / len(r["retrieved_rank"])
                    for r in rows
                )
                / n,
                2,
            )
            if n
            else 0.0
        )
        out[f"retrieved@{k}_hop0"] = sum(
            _within(list(r["retrieved_rank"].values())[0], k) for r in rows
        )
    docs = sorted(r["context_docs"] for r in rows)
    out["context_docs_median"] = docs[n // 2] if docs else 0
    return out


def stage_ranks(gold: list[str], rag_trace: dict, pool: list[tuple[str, float]]) -> dict:
    """Rank of each gold document at every pipeline stage (1-based, None if absent).

    ``rag_trace`` is ``RagTrace.to_dict()``; ``pool`` is the cross-encoder's output for
    the whole rerank pool as ``(doc_label, raw score)`` sorted by score.
    """
    phases = {p["name"]: p for p in rag_trace.get("phases", [])}
    channels = (phases.get("recall") or {}).get("channels") or {}

    def labels(cands: list[dict]) -> list[str]:
        return [c.get("doc_label", "") for c in cands]

    dense = labels((channels.get("dense") or {}).get("candidates") or [])
    graph = labels((channels.get("graph") or {}).get("candidates") or [])
    merged = (phases.get("merge_and_score") or {}).get("candidates") or []
    signal = {c.get("doc_label", ""): c.get("signal_score") for c in merged}
    found_by = {c.get("doc_label", ""): c.get("found_by") for c in merged}
    rerank = dict(pool)
    out = {}
    for g in gold:
        out[g] = {
            "dense": gold_positions([g], dense)[g],
            "graph": gold_positions([g], graph)[g],
            "found_by": found_by.get(g),
            "signal_rank": gold_positions([g], labels(merged))[g],
            "signal_score": signal.get(g),
            "rerank_rank": gold_positions([g], [label for label, _ in pool])[g],
            "rerank_score": rerank.get(g),
        }
    return out


def candidate_pool(rag_trace: dict, pool: list[tuple[str, float]]) -> list[dict]:
    """Every merged candidate with its channel scores and cross-encoder score (if pooled).

    Enough to replay any post-recall fusion offline without re-running the pipeline.
    """
    phases = {p["name"]: p for p in rag_trace.get("phases", [])}
    rerank = dict(pool)
    return [
        {
            "doc_label": c.get("doc_label", ""),
            "channel_scores": c.get("channel_scores") or {},
            "signal_score": c.get("signal_score"),
            "ce": rerank.get(c.get("doc_label", "")),
        }
        for c in (phases.get("merge_and_score") or {}).get("candidates") or []
    ]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--manifest", type=Path, default=Path("benchmarks/musique/data/manifest.jsonl")
    )
    parser.add_argument("--workspace", default="musique-dev")
    parser.add_argument("--graph", choices=sorted(GRAPH_MODES), default="bfs")
    parser.add_argument("--fusion", choices=FUSION_MODES, default="signal")
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--offset", type=int, default=0, help="skip the first N questions")
    parser.add_argument("--k", type=int, default=25, help="hybrid_search_and_answer k")
    parser.add_argument("--rerank-cache", type=Path, help="JSONL cross-encoder score cache")
    parser.add_argument("--trace", action="store_true", help="per-stage ranks of gold docs")
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="extra setting for this run (repeatable), e.g. RECALL_TOP_N_GRAPH=10",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    # Settings are read at import time: set the environment before importing metronix.
    os.environ.update(RETRIEVAL_ONLY_ENV)
    os.environ.update(GRAPH_MODES[args.graph])
    os.environ["METRONIX_RETRIEVAL_FUSION_MODE"] = args.fusion
    extra_env = dict(item.split("=", 1) for item in args.env)
    os.environ.update(extra_env)

    import asyncio
    import logging
    import uuid
    from unittest.mock import patch

    import structlog

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    from metronix.retrieval import reranker, search
    from metronix.retrieval.trace import RagTrace

    cache = None
    if args.rerank_cache:
        from benchmarks.musique.scripts.rerank_cache import install

        cache = install(args.rerank_cache)

    async def _no_graph(ctx, *a, **kw):
        return []

    with args.manifest.open(encoding="utf-8") as handle:
        manifest = [json.loads(line) for line in handle if line.strip()]
    manifest = manifest[args.offset : args.offset + args.limit]

    pool: list[tuple[str, float]] = []
    real_rerank = reranker.rerank

    def _recording_rerank(query, results, top_k=25):
        ranked = real_rerank(query=query, results=results, top_k=top_k)
        pool[:] = [(r.get("doc_label", ""), float(r.get("rerank_score", 0.0))) for r in ranked]
        return ranked

    patches = [
        patch.object(search, "chat_completion", return_value=""),
        patch.object(search, "chat_completion_with_retry", return_value="(stub answer)"),
        patch.object(reranker, "rerank", _recording_rerank),
    ]
    if args.graph == "off":
        patches += [
            patch.object(search, "recall_graph_async", _no_graph),
            patch.object(search, "recall_graph_ppr_async", _no_graph),
        ]

    rows: list[dict] = []
    for p in patches:
        p.start()
    try:
        for m in manifest:
            pool.clear()
            rag_trace = RagTrace(trace_id=uuid.uuid4()) if args.trace else None
            trace = asyncio.run(
                search.hybrid_search_and_answer(
                    m["question"],
                    k=args.k,
                    workspace_id=args.workspace,
                    return_trace=True,
                    rag_trace=rag_trace,
                )
            )
            row = score_row(m, trace)
            if rag_trace is not None:
                row["stages"] = stage_ranks(row["gold"], rag_trace.to_dict(), pool)
                row["candidates"] = candidate_pool(rag_trace.to_dict(), pool)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        for p in patches:
            p.stop()

    summary = {
        "graph": args.graph,
        "fusion": args.fusion,
        "workspace": args.workspace,
        "offset": args.offset,
        "env": extra_env,
        **aggregate(rows),
    }
    if cache is not None:
        summary["rerank_cache"] = {"hits": cache.hits, "misses": cache.misses}
    print(json.dumps(summary, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
