"""Latency percentiles for the benchmark runners.

Standalone (the runners' venv has no ``metronix``); byte-for-byte the same as
``scripts/run_eval.py::latency_summary``, kept honest by a parity test in the
main suite.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


def summarize(measurements_ms: Iterable[float]) -> dict[str, float]:
    """``{mean_ms, p50_ms, p95_ms, max_ms}`` with linear-interpolated percentiles."""
    ordered = sorted(float(m) for m in measurements_ms)
    if not ordered:
        raise ValueError("latency summary requires at least one measurement")

    def percentile(fraction: float) -> float:
        position = fraction * (len(ordered) - 1)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {
        "mean_ms": sum(ordered) / len(ordered),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "max_ms": ordered[-1],
    }


_PHASES = ("ingest_ms", "search_ms", "answer_ms", "total_ms")


def aggregate_latency(rows: Sequence[dict], *, phases: Sequence[str] = _PHASES) -> dict[str, Any]:
    """Per-phase percentile summary over the rows that recorded that phase.

    ``search_ms`` is the phase a retrieval-latency ceiling would gate on; it
    includes the MCP round-trip, not just server compute.
    """
    out: dict[str, Any] = {"count": len(rows), "phases": {}}
    for phase in phases:
        values = [float(r[phase]) for r in rows if isinstance(r.get(phase), (int, float))]
        if values:
            out["phases"][phase] = {"n": len(values), **summarize(values)}
    return out
