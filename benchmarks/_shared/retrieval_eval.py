"""Per-row recall@k for the benchmark runners, and its aggregation.

The benchmark runners run in an isolated venv without ``metronix`` installed, so
this carries a standalone ``recall_at_k``. It is byte-for-byte the same formula
as ``metronix.benchmarker.services.metrics.retrieval.recall_at_k``; a parity
test in the main suite keeps the two honest.

Each answers-JSONL row the runner produces carries, for a question with a known
evidence session:

    recall_at_5, recall_at_10  : float
    oracle_session_tags        : list[str]
    retrieved_session_tags     : list[str]
    recall_gate_eligible       : bool  (False for abstention / no-oracle rows)
    <group_key>                : question_type (LongMemEval) | category (LoCoMo)

recall@10 over the ``recall_gate_eligible`` rows is the retrieval gate.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

RECALL_KS: tuple[int, ...] = (5, 10)
SEARCH_K_FLOOR = max(RECALL_KS)
SCHEMA_VERSION = 1


def recall_at_k(retrieved: Sequence[str], expected: set[str], k: int) -> float:
    """``|top_k ∩ expected| / |expected|``. 0.0 when there is nothing to recall."""
    if not retrieved or not expected or k <= 0:
        return 0.0
    top_k = set(retrieved[:k])
    return sum(1 for item in expected if item in top_k) / len(expected)


def recall_row(
    oracle_tags: set[str],
    retrieved_tags: Sequence[str],
    *,
    eligible: bool,
    ks: Sequence[int] = RECALL_KS,
) -> dict[str, Any]:
    """The recall fields for one answers-JSONL row.

    ``eligible`` is the caller's non-abstention verdict; a row is only counted
    toward the gate when it is both non-abstention *and* has an oracle session.
    """
    retrieved = list(retrieved_tags)
    row: dict[str, Any] = {
        "oracle_session_tags": sorted(oracle_tags),
        "retrieved_session_tags": retrieved,
        "recall_gate_eligible": bool(eligible and oracle_tags),
    }
    for k in ks:
        row[f"recall_at_{k}"] = recall_at_k(retrieved, oracle_tags, k)
    return row


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate_recall(
    rows: Iterable[dict],
    *,
    ks: Sequence[int] = RECALL_KS,
    group_key: str = "question_type",
) -> dict[str, Any]:
    """Overall + per-group mean recall@k over the eligible rows."""
    rows = list(rows)
    eligible = [r for r in rows if r.get("recall_gate_eligible") is True]

    def recall_for(subset: list[dict]) -> dict[str, float]:
        return {
            str(k): _mean([float(r[f"recall_at_{k}"]) for r in subset if f"recall_at_{k}" in r])
            for k in ks
        }

    groups: dict[str, list[dict]] = {}
    for row in eligible:
        groups.setdefault(str(row.get(group_key, "unknown")), []).append(row)

    return {
        "schema_version": SCHEMA_VERSION,
        "recall_ks": list(ks),
        "group_key": group_key,
        "question_count": len(rows),
        "eligible_count": len(eligible),
        "excluded_count": len(rows) - len(eligible),
        "recall": recall_for(eligible),
        "by_group": {
            name: {"count": len(subset), "recall": recall_for(subset)}
            for name, subset in sorted(groups.items())
        },
    }


def gate_value(report: dict[str, Any], k: int = 10) -> float | None:
    """The number a recall gate compares — mean recall@k, or ``None`` when
    nothing was eligible (an all-abstention run cannot be gated)."""
    if report.get("eligible_count", 0) == 0:
        return None
    return report.get("recall", {}).get(str(k))
