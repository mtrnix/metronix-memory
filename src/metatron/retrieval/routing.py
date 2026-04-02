"""LLM-as-Router — intent classification for query routing.

Provides keyword gating plus LLM-based classification to decide
whether a query should use the schema-guided team-workflow pipeline
or standard retrieval. Also detects Jira-specific queries and results.
"""

from __future__ import annotations

import re
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from metatron.llm import chat_completion  # TODO: async migration

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------


def _extract_json_object(s: str) -> str:
    """Best-effort extraction of a JSON object from an LLM response.

    Handles code fences and leading prose. Returns ``"{}"`` when no
    valid ``{...}`` is found.
    """
    if not s:
        return "{}"
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return "{}"
    return s[start : end + 1]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TeamWorkflowRoutingDecision(BaseModel):
    route: Literal["schema_guided_team_workflow", "default"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = ""


# ---------------------------------------------------------------------------
# Routing prompts
# ---------------------------------------------------------------------------

TEAM_WORKFLOW_ROUTING_SYSTEM_PROMPT = """
You are a routing classifier for a hybrid RAG assistant.
Decide whether the user's question is about team work / team workflow (processes, collaboration, roles, ceremonies, handoffs, sprint flow, delivery workflow).
Return STRICT JSON only (no markdown, no code fences).
"""

_KEYWORD_GATE = [
    "team work",
    "teamwork",
    "team workflow",
    "workflow",
    "process",
    "processes",
    "collaboration",
    "handoff",
    "handoffs",
    "ceremony",
    "ceremonies",
    "sprint",
    "standup",
    "retrospective",
    "planning",
    "kanban",
    "scrum",
    # Russian
    "команд",
    "команда",
    "воркфлоу",
    "процесс",
    "процессы",
    "взаимодействие",
    "согласование",
    "передача",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def should_use_team_workflow_schema(question: str) -> bool:  # TODO: async migration
    """Return ``True`` when the question is about team work / team workflow.

    Uses a fast keyword gate to avoid unnecessary LLM calls, then
    confirms via an LLM JSON classifier.
    """
    q = (question or "").strip()
    if not q:
        return False

    ql = q.lower()
    if not any(k in ql for k in _KEYWORD_GATE):
        return False

    content = chat_completion(
        messages=[
            {"role": "system", "content": TEAM_WORKFLOW_ROUTING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "User question:\n"
                    f"{q}\n\n"
                    "Return JSON with fields:\n"
                    '- route: "schema_guided_team_workflow" or "default"\n'
                    "- confidence: number 0..1\n"
                    "- rationale: short string\n"
                ),
            },
        ],
        temperature=0.1,
        max_tokens=200,
        json_mode=True,
        timeout=20,
    )
    decision = TeamWorkflowRoutingDecision.model_validate_json(_extract_json_object(content))
    return decision.route == "schema_guided_team_workflow"


# ---------------------------------------------------------------------------
# Jira detection helpers
# ---------------------------------------------------------------------------


def is_jira_result(mem: dict) -> bool:
    """Return ``True`` if the search result dict originates from Jira."""
    t = (mem.get("type") or "").lower()
    if t == "jira":
        return True
    meta = mem.get("metadata") or {}
    t = (meta.get("type") or "").lower()
    if t == "jira":
        return True
    # Heuristic: MTRNIX-123 pattern in content
    mem_text = (mem.get("memory") or mem.get("data") or "")[:100]
    return bool(re.search(r"\b[A-Z]{2,}-\d+\b", mem_text))


def is_jira_query(query: str) -> bool:
    """Return ``True`` if the query targets Jira tickets."""
    ql = query.lower()
    jira_keywords = [
        "jira",
        "ticket",
        "issue",
        "bug",
        "task",
        "mtrnix-",
        "тикет",
        "задача",
    ]
    return any(w in ql for w in jira_keywords) or bool(
        re.search(r"\b[A-Z]{2,}-\d+\b", query, flags=re.IGNORECASE)
    )
