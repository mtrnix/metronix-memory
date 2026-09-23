"""Issue #497 real-corpus audit: raw per-channel scores BEFORE compute_signal_score.

Runs real queries -- grounded in the documents actually indexed in the MTRNIX
workspace right now (KB-* notes + QA-AURORA-* runbook/update fixtures; verified
via a Qdrant scroll + Neo4j entity dump before writing this query list) -- through
the production recall pipeline: _build_recall_context() + the four
recall_*_async() channels + merge_channels(), exactly as hybrid_search_and_answer()
does it. Logs the channel_scores dict per merged candidate BEFORE it reaches
compute_signal_score(), so the audit sees exactly what issue #497 is about.

Must run where Qdrant/Neo4j/Ollama are reachable -- i.e. inside the
metronix-core container:

    docker cp scripts/audits/issue-497/audit_channel_scores.py metronix-full-api:/tmp/
    docker exec -e METRONIX_RETRIEVAL_GRAPH_PPR_ENABLED=false metronix-full-api \
        python /tmp/audit_channel_scores.py

Raw output from the 2026-09-16 run (40 queries against the MTRNIX dev-fixture
corpus) is checked in alongside this script as audit_results_2026-09-16.json --
see issue #497 for the full write-up and analysis.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from collections import Counter, defaultdict

from metronix.core.config import Settings
from metronix.retrieval.channels import merge_channels
from metronix.retrieval.search import (
    _build_recall_context,
    _run_recall_channels_async,
    classify_query,
    detect_response_language,
    expand_query,
    resolve_query,
    translate_query_to_english,
)

WORKSPACE = "MTRNIX"

# (query_text, tag) -- tag is our own bookkeeping label for which channel(s)
# the query is *designed* to probe, not an assertion about what will fire.
QUERIES: list[tuple[str, str]] = [
    # -- entity queries: 2-word capitalized names extracted by
    # extract_title_entities() -> should feed both `exact` (scroll_by_title)
    # and `graph` (BFS seed) channels, both backed by search_by_doc_labels /
    # scroll_by_title, i.e. the hardcoded score=1.0 path in storage/qdrant.py.
    ("What is the Project Aurora deployment runbook?", "entity"),
    ("Tell me about Project Aurora", "entity"),
    ("Who is the tech lead for Project Aurora?", "entity"),
    ("Who is Dana Ivanova?", "entity"),
    ("What does Marcus Webb do?", "entity"),
    ("Tell me about Marcus Webb", "entity"),
    ("What team maintains Project Aurora now?", "entity"),
    ("How does Project Aurora depend on the Helios connector?", "entity"),
    ("What is the Vega warehouse used for?", "entity"),
    ("What is the rollback threshold for Project Aurora?", "entity"),
    ("Who owns the Titan fleet?", "entity"),
    ("Tell me about the Reliability team", "entity"),
    # -- dense-only: generic semantic questions about real KB note content,
    # no 2-word proper noun, no date, no activity keyword, no assignee.
    ("How does Metronix's hybrid retrieval pipeline work?", "dense"),
    ("What is search_fast used for?", "dense"),
    ("Where does agent memory get stored?", "dense"),
    ("What does metronix_memory_search do?", "dense"),
    ("What is a cross-encoder reranker?", "dense"),
    ("How does reciprocal rank fusion combine channels?", "dense"),
    ("What is the purpose of the url probe document?", "dense"),
    ("What was verified in the url fix branch?", "dense"),
    ("What does the Nimbus scheduler do?", "dense"),
    ("Who owns the Cirrus pool?", "dense"),
    ("What replaced the digit-only placeholder content?", "dense"),
    ("Explain SPLADE sparse retrieval", "dense"),
    # -- metadata: date / activity-status / assignee signals
    ("What happened on 2026-09-05?", "metadata-date"),
    ("What was updated last week?", "metadata-date"),
    ("What changed on 2026-08-31?", "metadata-date"),
    ("What's in the current sprint?", "metadata-activity"),
    ("What's in the backlog?", "metadata-activity"),
    ("What tasks are in progress right now?", "metadata-activity"),
    ("What is Dana working on?", "metadata-person"),
    ("What is Marcus doing?", "metadata-person"),
    # -- Russian (translation pipeline)
    ("Что такое Project Aurora?", "russian-entity"),
    ("Расскажи про поиск в Metronix", "russian-dense"),
    ("Кто такой Marcus Webb?", "russian-entity"),
    # -- typos / fuzzy
    ("Projekt Arora deployment", "typo"),
    ("Nimbis scheduler owner", "typo"),
    # -- negative / vague / greeting
    ("How do I configure Kubernetes?", "negative"),
    ("Tell me everything", "vague"),
    ("Hello", "greeting"),
]


def _result_type(r: dict) -> str:
    return (
        r.get("type")
        or (r.get("payload") or {}).get("type")
        or (r.get("metadata") or {}).get("type")
        or "unknown"
    ).lower()


async def run_one(settings: Settings, query_text: str, tag: str) -> dict:
    rq = resolve_query(query_text)
    lang = detect_response_language(rq)
    eq = expand_query(rq)
    has_cyr = any("Ѐ" <= c <= "ӿ" for c in eq)
    sq = translate_query_to_english(eq) if has_cyr else eq

    if settings.query_classifier_enabled:
        classification = classify_query(rq, translated_query=sq)
    else:
        classification = {"profile": "mixed", "confidence": 1.0, "method": "disabled"}

    recall_ctx = _build_recall_context(
        original_query=rq,
        translated_query=sq,
        expanded_query=eq,
        detected_language=lang,
        workspace_id=WORKSPACE,
        access_filter=None,
        settings=settings,
    )

    dense_r, exact_r, metadata_r, graph_r = await _run_recall_channels_async(recall_ctx)
    merged = merge_channels([dense_r, exact_r, metadata_r, graph_r])

    candidates = [
        {
            "chunk_id": mr["chunk_id"],
            "doc_label": mr["doc_label"],
            "channels": mr["channels"],
            "channel_scores": mr["channel_scores"],
            "source_type": _result_type(mr["memory"]),
        }
        for mr in merged
    ]

    return {
        "query": query_text,
        "tag": tag,
        "resolved_query": rq,
        "expanded_query": eq,
        "translated_query": sq,
        "profile": classification["profile"],
        "extracted_jira_keys": recall_ctx.extracted_jira_keys,
        "extracted_title_entities": recall_ctx.extracted_title_entities,
        "extracted_dates": recall_ctx.extracted_dates,
        "detected_person": recall_ctx.detected_person,
        "is_activity_query": recall_ctx.is_activity_query,
        "recall_counts": {
            "dense": len(dense_r),
            "exact": len(exact_r),
            "metadata": len(metadata_r),
            "graph": len(graph_r),
        },
        "candidates": candidates,
    }


def _analyze(results: list[dict]) -> None:
    channel_values: dict[str, list[float]] = defaultdict(list)
    channel_query_hits: dict[str, int] = Counter()
    queries_with_any_hit = 0
    channel_pairs_with_dense: list[
        tuple[str, float, float]
    ] = []  # (query, other_score, dense_score)

    for r in results:
        if "error" in r:
            continue
        fired = {ch for ch, n in r["recall_counts"].items() if n > 0}
        if fired:
            queries_with_any_hit += 1
        for ch in fired:
            channel_query_hits[ch] += 1

        dense_scores_here = [
            c["channel_scores"]["dense"] for c in r["candidates"] if "dense" in c["channel_scores"]
        ]
        max_dense_here = max(dense_scores_here) if dense_scores_here else None

        for c in r["candidates"]:
            for ch, val in c["channel_scores"].items():
                channel_values[ch].append(val)
                if ch != "dense" and max_dense_here is not None:
                    channel_pairs_with_dense.append((r["query"], ch, val, max_dense_here))

    n_queries = sum(1 for r in results if "error" not in r)
    n_errors = sum(1 for r in results if "error" in r)

    print("=" * 78)
    print("ISSUE #497 -- REAL-CORPUS CHANNEL SCORE AUDIT")
    print("=" * 78)
    print(f"queries run: {n_queries}  (errors: {n_errors})")
    print(f"queries with >=1 channel firing: {queries_with_any_hit}/{n_queries}")
    print()
    print("channel firing rate (fraction of queries where this channel returned >=1 result):")
    for ch in ("dense", "exact", "metadata", "graph"):
        n = channel_query_hits.get(ch, 0)
        print(f"  {ch:9s}: {n:2d}/{n_queries}  ({n / n_queries * 100:5.1f}%)")
    print()

    print("raw score distribution per channel, across ALL (query, candidate) pairs:")
    print(
        f"{'channel':10s} {'n':>5s} {'min':>8s} {'max':>8s} {'mean':>8s} "
        f"{'==1.0':>8s} {'%==1.0':>8s}"
    )
    for ch, vals in channel_values.items():
        n = len(vals)
        n_exactly_one = sum(1 for v in vals if v == 1.0)
        print(
            f"{ch:10s} {n:5d} {min(vals):8.4f} {max(vals):8.4f} "
            f"{statistics.mean(vals):8.4f} {n_exactly_one:8d} {n_exactly_one / n * 100:7.1f}%"
        )
    print()

    if channel_pairs_with_dense:
        print(
            "worked example: (query, non-dense channel, its raw score, "
            "max dense score in same query)"
        )
        # show a spread: a few where the non-dense score is 1.0 and dense is small
        shown = 0
        for q, ch, val, dense in channel_pairs_with_dense:
            if val == 1.0 and dense < 0.05:
                print(
                    f"  [{ch:8s}] score={val:.4f}  vs  max_dense={dense:.4f}  "
                    f"(ratio {val / dense:6.1f}x)  <- {q!r}"
                )
                shown += 1
            if shown >= 10:
                break
        if shown == 0:
            print(
                "  (no case found where a non-dense channel hit 1.0 alongside a weak dense score)"
            )
    print()

    print("per-query detail (channel counts + is any non-dense score exactly 1.0):")
    for r in results:
        if "error" in r:
            print(f"  ERROR  {r['query']!r}: {r['error']}")
            continue
        counts = r["recall_counts"]
        non_dense_ones = sorted(
            {
                ch
                for c in r["candidates"]
                for ch, v in c["channel_scores"].items()
                if ch != "dense" and v == 1.0
            }
        )
        dense_vals = [
            c["channel_scores"].get("dense")
            for c in r["candidates"]
            if "dense" in c["channel_scores"]
        ]
        max_dense = max(dense_vals) if dense_vals else None
        print(
            f"  [{r['tag']:16s}] d={counts['dense']:2d} e={counts['exact']:2d} "
            f"m={counts['metadata']:2d} g={counts['graph']:2d}  "
            f"max_dense={max_dense if max_dense is None else round(max_dense, 4)}  "
            f"const1.0_in={non_dense_ones or '-'}  {r['query']!r}"
        )


async def main() -> None:
    settings = Settings()
    print(f"retrieval_graph_ppr_enabled = {settings.retrieval_graph_ppr_enabled}")
    print(f"query_classifier_enabled = {settings.query_classifier_enabled}")
    normalize_active_only = settings.retrieval_scoring_normalize_active_only
    print(f"retrieval_scoring_normalize_active_only = {normalize_active_only}")
    print(f"workspace = {WORKSPACE}")
    print(f"queries = {len(QUERIES)}")
    print()

    results = []
    for i, (q, tag) in enumerate(QUERIES):
        try:
            r = await run_one(settings, q, tag)
        except Exception as e:  # noqa: BLE001 -- audit script, keep going on any single failure
            r = {"query": q, "tag": tag, "error": repr(e)}
        results.append(r)
        print(f"[{i + 1}/{len(QUERIES)}] {q!r} -> counts={r.get('recall_counts')}")

    out_path = "/tmp/audit_497_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nSaved raw results to {out_path}")
    print()

    _analyze(results)


if __name__ == "__main__":
    asyncio.run(main())
