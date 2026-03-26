"""Query classifier for source-of-truth profiles.

Classifies incoming queries into 6 intent profiles and returns weight
presets for compute_signal_score() and compute_final_score().

Hybrid approach: fast rule gate for obvious cases, LLM fallback for ambiguous.
Any failure gracefully degrades to 'mixed' (current defaults).
"""

from __future__ import annotations

from typing import TypedDict

import structlog

logger = structlog.get_logger()


class QueryClassification(TypedDict):
    profile: str       # "execution" | "documentation" | "user_file" | "relationship" | "temporal" | "mixed"
    confidence: float  # 0.0 - 1.0
    method: str        # "rule" | "llm" | "default" | "disabled"


QUERY_PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "execution":     {"dense_weight": 0.20, "sparse_weight": 0.0, "graph_weight": 0.10, "metadata_weight": 0.35, "recency_weight": 0.15, "balance_weight": 0.05, "blend_weight": 0.25},
    "documentation": {"dense_weight": 0.45, "sparse_weight": 0.0, "graph_weight": 0.15, "metadata_weight": 0.15, "recency_weight": 0.05, "balance_weight": 0.05, "blend_weight": 0.35},
    "user_file":     {"dense_weight": 0.45, "sparse_weight": 0.0, "graph_weight": 0.05, "metadata_weight": 0.20, "recency_weight": 0.05, "balance_weight": 0.10, "blend_weight": 0.35},
    "relationship":  {"dense_weight": 0.25, "sparse_weight": 0.0, "graph_weight": 0.35, "metadata_weight": 0.15, "recency_weight": 0.05, "balance_weight": 0.05, "blend_weight": 0.25},
    "temporal":      {"dense_weight": 0.25, "sparse_weight": 0.0, "graph_weight": 0.10, "metadata_weight": 0.15, "recency_weight": 0.30, "balance_weight": 0.05, "blend_weight": 0.30},
    "mixed":         {"dense_weight": 0.35, "sparse_weight": 0.0, "graph_weight": 0.15, "metadata_weight": 0.20, "recency_weight": 0.10, "balance_weight": 0.05, "blend_weight": 0.30},
}


def get_profile_weights(profile: str) -> dict[str, float]:
    """Return weight preset for the given profile. Falls back to 'mixed' if unknown."""
    return QUERY_PROFILE_WEIGHTS.get(profile, QUERY_PROFILE_WEIGHTS["mixed"])
