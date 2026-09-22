"""Issue #488 baseline: ID-duplication rate in top-k search results, BEFORE
any cleanup of already-accumulated duplicate Qdrant chunks.

"Duplicate" here means the #461 phenomenon: the ingest path stamps every
chunk with a fresh random ``uuid4()`` Qdrant point id (see
``storage/qdrant.py`` -- ``qdrant_id = str(uuid.uuid4())``), so a re-ingested,
byte-identical chunk gets a *new* point id sitting alongside the old one.
Two results can therefore never collide on Qdrant point id itself -- the
duplication signal is a top-k slot whose (doc_label, content) pair repeats an
earlier-ranked slot in the *same* query's results, with a different
underlying id. That is exactly what #461 observed: "metronix_search_fast
returns the same document as several separate hits with near-identical
scores".

Runs through ``fast_search()`` -- the production code path behind the
``metronix_search_fast`` MCP tool, the same tool #461's repro used -- against
the same 40-query, real-corpus query set used for the issue #497 channel-score
audit (``scripts/audits/issue-497/audit_channel_scores.py``), reused here
via import rather than copied, so both audits stay in sync if the query set
changes.

Must run where Qdrant/Neo4j/Ollama are reachable -- i.e. inside the
metronix-core container:

    docker cp scripts/audits/issue-488/baseline_duplication_rate.py \
        metronix-full-api:/tmp/
    docker cp scripts/audits/issue-497/audit_channel_scores.py \
        metronix-full-api:/tmp/issue_497_audit_channel_scores.py
    docker exec metronix-full-api \
        python /tmp/baseline_duplication_rate.py

CAVEAT (read before citing this number): this ran against the MTRNIX
dev-fixture workspace (9 Qdrant points total -- KB-* notes + QA-AURORA-*
runbook/update fixtures), not a production customer index. It captures
*whether any already-accumulated duplication is currently visible in top-k
results in this environment*, not a production-representative duplication
rate. If a production index is available, re-run against it before using
this number to size or prioritize the #488 cleanup.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import math
import statistics
from pathlib import Path

WORKSPACE = "MTRNIX"
TOP_K = 10  # metronix_search_fast's own default

_AUDIT_497_PATH = Path(__file__).resolve().parent.parent / "issue-497" / "audit_channel_scores.py"


def _load_query_set() -> list[tuple[str, str]]:
    """Import QUERIES from the #497 audit script without needing it on sys.path
    under its own package (it isn't one)."""
    candidates = [
        _AUDIT_497_PATH,
        Path("/tmp/issue_497_audit_channel_scores.py"),
    ]
    for path in candidates:
        if path.is_file():
            spec = importlib.util.spec_from_file_location("issue_497_audit", path)
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.QUERIES
    raise FileNotFoundError(
        "Could not find the #497 audit script's QUERIES list. Copy "
        "scripts/audits/issue-497/audit_channel_scores.py to "
        "/tmp/issue_497_audit_channel_scores.py alongside this script."
    )


def _content_key(hit: dict) -> str:
    """Stable dedup key: doc_label + a hash of the chunk text.

    Falls back across the field names the qdrant hit dict actually uses
    (``data`` is primary, ``memory`` is the backward-compat mirror -- see
    ``QdrantStore.add_document``).
    """
    doc_label = str(hit.get("doc_label") or "")
    text = str(hit.get("data") or hit.get("memory") or "")
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{doc_label}::{text_hash}"


def _wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a pooled binomial proportion (slots as trials).

    Ignores within-query clustering -- see the bootstrap CI below for the
    clustering-aware estimate, which is the one to actually trust.
    """
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return ((centre - margin) / denom, (centre + margin) / denom)


def _bootstrap_ci(
    per_query_rates: list[float], iterations: int = 10000, seed: int = 488
) -> tuple[float, float]:
    """Percentile bootstrap CI over per-query duplication rates.

    This is the CI that matters: it resamples whole queries, so it accounts
    for slots within one query not being independent trials (they share a
    query, an index state, and whatever made that query prone to
    duplication).
    """
    import random

    if not per_query_rates:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(per_query_rates)
    means = []
    for _ in range(iterations):
        sample = [per_query_rates[rng.randrange(n)] for _ in range(n)]
        means.append(statistics.fmean(sample))
    means.sort()
    lo_idx = int(0.025 * iterations)
    hi_idx = int(0.975 * iterations) - 1
    return (means[lo_idx], means[hi_idx])


async def run_one(query_text: str, tag: str) -> dict:
    from metronix.retrieval.search import fast_search

    try:
        hits = await fast_search(query_text, workspace_id=WORKSPACE, top_k=TOP_K)
    except Exception as exc:  # noqa: BLE001 — recorded, not raised, so one bad query doesn't kill the run
        return {"query": query_text, "tag": tag, "error": str(exc)}

    seen: set[str] = set()
    slots = []
    for hit in hits:
        key = _content_key(hit)
        is_dup = key in seen
        seen.add(key)
        slots.append(
            {
                "point_id": str(hit.get("id", "")),
                "doc_label": hit.get("doc_label", ""),
                "content_key": key,
                "is_duplicate_of_earlier_slot": is_dup,
            }
        )

    n_slots = len(slots)
    n_dup = sum(1 for s in slots if s["is_duplicate_of_earlier_slot"])
    return {
        "query": query_text,
        "tag": tag,
        "n_slots": n_slots,
        "n_dup_slots": n_dup,
        "dup_rate": (n_dup / n_slots) if n_slots else None,
        "slots": slots,
    }


async def main() -> None:
    queries = _load_query_set()
    results = [await run_one(q, tag) for q, tag in queries]

    errors = [r for r in results if "error" in r]
    ok = [r for r in results if "error" not in r]

    total_slots = sum(r["n_slots"] for r in ok)
    total_dup = sum(r["n_dup_slots"] for r in ok)
    per_query_rates = [r["dup_rate"] for r in ok if r["dup_rate"] is not None]

    pooled_rate = (total_dup / total_slots) if total_slots else 0.0
    wilson_lo, wilson_hi = _wilson_ci(total_dup, total_slots)
    boot_lo, boot_hi = _bootstrap_ci(per_query_rates) if per_query_rates else (0.0, 0.0)

    print("=" * 78)
    print("ISSUE #488 -- BASELINE ID-DUPLICATION RATE (pre-cleanup)")
    print("=" * 78)
    print(f"workspace: {WORKSPACE}   top_k: {TOP_K}")
    print(f"queries: {len(queries)}   ok: {len(ok)}   errors: {len(errors)}")
    print()
    print(f"total top-k slots examined: {total_slots}")
    print(f"total duplicate slots:      {total_dup}")
    print(f"pooled duplicate rate:      {pooled_rate:.4f}")
    print(
        f"  Wilson 95% CI (slot-level, ignores query clustering): "
        f"[{wilson_lo:.4f}, {wilson_hi:.4f}]"
    )
    print(
        f"  bootstrap 95% CI (query-level resampling, n={len(per_query_rates)} queries): "
        f"[{boot_lo:.4f}, {boot_hi:.4f}]"
    )
    print()
    print("queries with >=1 duplicate slot:")
    for r in ok:
        if r["n_dup_slots"] > 0:
            dup_labels = sorted(
                {s["doc_label"] for s in r["slots"] if s["is_duplicate_of_earlier_slot"]}
            )
            print(
                f"  [{r['tag']:16}] {r['n_dup_slots']}/{r['n_slots']} dup  "
                f"query={r['query']!r}  doc_labels={dup_labels}"
            )
    if not any(r["n_dup_slots"] > 0 for r in ok):
        print("  (none)")
    print()
    if errors:
        print("queries that errored:")
        for r in errors:
            print(f"  [{r['tag']}] {r['query']!r}: {r['error']}")
        print()

    out_path = Path(__file__).resolve().parent / "baseline_results.json"
    out_path.write_text(
        json.dumps(
            {
                "workspace": WORKSPACE,
                "top_k": TOP_K,
                "n_queries": len(queries),
                "n_ok": len(ok),
                "n_errors": len(errors),
                "total_slots": total_slots,
                "total_dup_slots": total_dup,
                "pooled_dup_rate": pooled_rate,
                "wilson_95ci": [wilson_lo, wilson_hi],
                "bootstrap_95ci_query_level": [boot_lo, boot_hi],
                "per_query": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
