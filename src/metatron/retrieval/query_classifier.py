"""Query classifier for source-of-truth profiles.

Classifies incoming queries into 6 intent profiles and returns weight
presets for compute_signal_score() and compute_final_score().

Hybrid approach: fast rule gate for obvious cases, LLM fallback for ambiguous.
Any failure gracefully degrades to 'mixed' (current defaults).
"""

from __future__ import annotations

import json
import re
from typing import TypedDict

import structlog

from metatron.ingestion.processors.dates import extract_date_range
from metatron.llm import chat_completion

logger = structlog.get_logger()


class QueryClassification(TypedDict):
    # "execution" | "documentation" | "user_file" | "relationship" | "temporal" | "mixed"
    profile: str
    confidence: float  # 0.0 - 1.0
    method: str        # "rule" | "llm" | "default" | "disabled"


# NOTE: When the classifier is enabled, these weights OVERRIDE the per-signal
# weights from Settings (dense_weight, graph_weight, etc.). Env var tuning of
# individual weights has no effect while the classifier is active.
# Disable the classifier (QUERY_CLASSIFIER_ENABLED=False) to use Settings weights.
QUERY_PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "execution": {
        "dense_weight": 0.20,
        "graph_weight": 0.10,
        "metadata_weight": 0.35,
        "recency_weight": 0.15,
        "balance_weight": 0.05,
        "blend_weight": 0.25,
    },
    "documentation": {
        "dense_weight": 0.45,
        "graph_weight": 0.15,
        "metadata_weight": 0.15,
        "recency_weight": 0.05,
        "balance_weight": 0.05,
        "blend_weight": 0.35,
    },
    "user_file": {
        "dense_weight": 0.45,
        "graph_weight": 0.05,
        "metadata_weight": 0.20,
        "recency_weight": 0.05,
        "balance_weight": 0.10,
        "blend_weight": 0.35,
    },
    "relationship": {
        "dense_weight": 0.25,
        "graph_weight": 0.35,
        "metadata_weight": 0.15,
        "recency_weight": 0.05,
        "balance_weight": 0.05,
        "blend_weight": 0.25,
    },
    "temporal": {
        "dense_weight": 0.25,
        "graph_weight": 0.10,
        "metadata_weight": 0.15,
        "recency_weight": 0.30,
        "balance_weight": 0.05,
        "blend_weight": 0.30,
    },
    "mixed": {
        "dense_weight": 0.35,
        "graph_weight": 0.15,
        "metadata_weight": 0.20,
        "recency_weight": 0.10,
        "balance_weight": 0.05,
        "blend_weight": 0.30,
    },
}


def get_profile_weights(profile: str) -> dict[str, float]:
    """Return weight preset for the given profile. Falls back to 'mixed' if unknown."""
    return QUERY_PROFILE_WEIGHTS.get(profile, QUERY_PROFILE_WEIGHTS["mixed"])


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
    r'\bfile\b|\buploaded\b|\bpdf\b|\b10K\b'
    r'|\bфайл|\bзагруженн|\bотчет\b',
    re.IGNORECASE,
)

_RELATIONSHIP_KW = re.compile(
    r'\brelationship\w*\b|\brelate[ds]?\b|\bconnect\w*\b|\bdepend\w*\b'
    r'|\bbetween\b|\blinked\b'
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


_CLASSIFIER_SYSTEM_PROMPT = """\
You are a query intent classifier. Given a search query, classify it into one of 6 profiles.

Profiles:
- "execution": Task status, Jira tickets, current work, sprint, who is doing what. \
Examples: "What is the status of MTRNIX-104?", "What tasks are in progress?"
- "documentation": Architecture, concepts, explanations, how things work. \
Examples: "What is Metatron?", "How does RBAC work?"
- "user_file": Questions about uploaded files, reports, PDFs. \
Examples: "What does the 10K report say?", "Summarize the uploaded document"
- "relationship": Connections between entities, dependencies, links. \
Examples: "How does RBAC relate to user docs?", "What depends on the auth module?"
- "temporal": Date-bound, recent activity, sprints, time ranges. \
Examples: "What was done last week?", "Show documentation updated in 2026"
- "mixed": Unclear intent or spans multiple categories. Use when unsure.

Respond with JSON only: {"profile": "<name>", "confidence": <0.0-1.0>}"""

_VALID_PROFILES = frozenset(QUERY_PROFILE_WEIGHTS.keys())


def _llm_classify(query: str) -> QueryClassification:
    """Classify query via LLM. Returns mixed on any failure."""
    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=60,
            timeout=10,
        )
        parsed = json.loads(raw.strip())
        profile = parsed.get("profile", "mixed")
        confidence = float(parsed.get("confidence", 0.0))

        if profile not in _VALID_PROFILES or confidence < 0.5:
            return {"profile": "mixed", "confidence": confidence, "method": "default"}

        return {"profile": profile, "confidence": confidence, "method": "llm"}
    except Exception:
        logger.warning("query_classifier.llm_failed", query=query[:100])
        return {"profile": "mixed", "confidence": 0.0, "method": "default"}


def classify_query(
    query: str,
    translated_query: str | None = None,
) -> QueryClassification:
    """Classify query intent into a profile for weight selection.

    Uses rule gate first (fast, deterministic). Falls back to LLM for
    ambiguous queries. Any exception returns 'mixed' (graceful degradation).

    Args:
        query: Original user query (rq).
        translated_query: English translation of query (for Russian queries).
            If None, only the original query is checked by the rule gate.
    """
    try:
        # Rule gate: check original query
        profile = _rule_gate(query)

        # For Russian queries, also check translated version for English keywords
        if profile is None and translated_query and translated_query != query:
            profile = _rule_gate(translated_query)

        if profile is not None:
            logger.info("query_classifier.rule", profile=profile, query=query[:100])
            return {"profile": profile, "confidence": 1.0, "method": "rule"}

        # LLM fallback — use translated query for better classification if available
        llm_input = translated_query if translated_query and translated_query != query else query
        result = _llm_classify(llm_input)
        logger.info(
            "query_classifier.llm",
            profile=result["profile"],
            confidence=result["confidence"],
            query=query[:100],
        )
        return result
    except Exception:
        logger.warning("query_classifier.failed", query=query[:100])
        return {"profile": "mixed", "confidence": 0.0, "method": "default"}
