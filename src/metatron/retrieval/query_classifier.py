"""Query classifier for source-of-truth profiles.

Classifies incoming queries into 6 intent profiles and returns weight
presets for compute_signal_score() and compute_final_score().

Hybrid approach: fast rule gate for obvious cases, LLM fallback for ambiguous.
Any failure gracefully degrades to 'mixed' (current defaults).
"""

from __future__ import annotations

import re
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


from metatron.ingestion.processors.dates import extract_date_range  # noqa: E402

# -- Rule gate patterns (per profile) --

_JIRA_KEY_RE = re.compile(r'\b[A-Z]{2,}-\d+\b', re.IGNORECASE)

_EXECUTION_KW = re.compile(
    r'\bin progress\b|\bsprint\b|\bbacklog\b'
    r'|\bв работе\b|\bтекущий спринт\b',
    re.IGNORECASE,
)

_TEMPORAL_KW = re.compile(
    r'\bthis month\b|\blast week\b|\blast month\b|\brecently\b|\bthis week\b'
    r'|\bна этой неделе\b|\bза последний месяц\b|\bна прошлой неделе\b|\bнедавно\b',
    re.IGNORECASE,
)

_USER_FILE_KW = re.compile(
    r'\bfile\b|\buploaded\b|\bpdf\b|\breport\b|\b10K\b'
    r'|\bфайл|\bзагруженн|\bотчет\b',
    re.IGNORECASE,
)

_RELATIONSHIP_KW = re.compile(
    r'\brelat\w*\b|\bconnect\w*\b|\bdepend\w*\b|\bbetween\b|\blinked\b'
    r'|\bсвязан\w*\b|\bзависи\w*\b|\bмежду\b',
    re.IGNORECASE,
)


def _rule_gate(query: str) -> str | None:
    """Fast deterministic classification via keyword/regex rules.

    Returns a profile name if exactly one profile matches.
    Returns None if 0 or 2+ profiles match (caller should use LLM fallback).
    """
    matched: set[str] = set()

    # execution: Jira key or status keywords
    if _JIRA_KEY_RE.search(query) or _EXECUTION_KW.search(query):
        matched.add("execution")

    # temporal: date expressions or time keywords
    try:
        date_range = extract_date_range(query)
    except Exception:
        date_range = None
    if date_range or _TEMPORAL_KW.search(query):
        matched.add("temporal")

    # user_file: upload/file keywords
    if _USER_FILE_KW.search(query):
        matched.add("user_file")

    # relationship: entity connection keywords
    if _RELATIONSHIP_KW.search(query):
        matched.add("relationship")

    # documentation has no rule gate (too broad, handled by LLM)

    if len(matched) == 1:
        return matched.pop()
    return None
