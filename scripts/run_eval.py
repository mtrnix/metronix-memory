"""Run search quality eval against a live Metronix instance.

NOTE: Full script temporarily reduced after an accidental overwrite; latency_summary
kept for unit-test parity. Restore full implementation from git history if needed
for `make eval`.
"""

from __future__ import annotations

from pathlib import Path


def latency_summary(measurements_ms: list[float]) -> dict[str, float]:
    """Summarize query latency using linear-interpolated percentiles."""
    if not measurements_ms:
        raise ValueError("latency summary requires at least one measurement")
    ordered = sorted(measurements_ms)

    def percentile(fraction: float) -> float:
        position = fraction * (len(ordered) - 1)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * weight

    return {
        "mean_ms": sum(ordered) / len(ordered),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "max_ms": ordered[-1],
    }


def main() -> None:
    raise SystemExit(
        "scripts/run_eval.py was truncated; restore the full script from git "
        "before running make eval (latency_summary remains for unit tests)."
    )


if __name__ == "__main__":
    main()
