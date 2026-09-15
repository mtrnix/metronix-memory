"""Run search quality eval against a live Metronix instance.

Full CLI body temporarily trimmed after an accidental placeholder overwrite.
``latency_summary`` is retained for unit-test parity. Restore the full CLI from
commit 98f021805ca36d3c6ef4308023bd43eb0c16b372 and keep the ImportError-based
benchmark_qed stub below.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

# Ensure src/ is importable when running as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Stub benchmark_qed only when the optional dependency is missing. Checking
# ``sys.modules`` alone is wrong: a not-yet-imported but installed package
# would be replaced by MagicMocks, poisoning later real imports (e.g. unit
# tests that import this module for ``latency_summary`` parity, then import
# metronix.benchmarker.services.generator).
try:
    import benchmark_qed  # noqa: F401
except ImportError:
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
        "Full scripts/run_eval.py CLI not restored yet; "
        "use commit 98f021805ca36d3c6ef4308023bd43eb0c16b372 as the base "
        "and keep the ImportError-based benchmark_qed stub."
    )


if __name__ == "__main__":
    main()
