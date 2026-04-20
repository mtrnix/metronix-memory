"""DecisionEngine — classifies a memory record for the freshness pipeline.

Two implementations:

* ``RuleBasedDecisionEngine`` — zero-LLM heuristic. Returns confidence
  in ``[0.5, 0.6)`` based on simple keyword extraction. Used when no
  ``METATRON_FRESHNESS_LLM_API_BASE_URL`` is configured.
* ``LLMBackedDecisionEngine`` — calls an SLM (e.g. qwen2.5-4b) through the
  existing sync ``LLMProvider`` via ``asyncio.to_thread``. On malformed
  output or provider failure it falls back to ``RuleBasedDecisionEngine``.

``apply_decision`` turns a ``FreshnessDecision`` into a PG side-effect:
above the confidence threshold it writes lifecycle/tag changes, below it
creates a ``ReviewEntry(reason="low_confidence_decision")``.

The protocol lives in this module (not in ``core/interfaces.py``) per
Phase A — lift it up only when MTRNIX-313 adds a second call site.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

from metatron.core.config import get_settings
from metatron.core.models import FreshnessDecision, ReviewEntry
from metatron.llm.base import Message

if TYPE_CHECKING:
    from metatron.core.models import MemoryRecord
    from metatron.llm.base import LLMProvider
    from metatron.storage.memory_freshness_pg import FreshnessPostgresStore
    from metatron.storage.memory_postgres import MemoryPostgresStore

logger = structlog.get_logger()


_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "have",
        "has",
        "are",
        "was",
        "were",
        "will",
        "not",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
        "is",
        "it",
        "be",
        "as",
        "by",
        "at",
        "or",
        "if",
    }
)


def _extract_keywords(content: str, *, limit: int = 5) -> list[str]:
    """Very cheap keyword extractor for the rule-based fallback.

    Picks the first N unique lowercase tokens that look like words,
    excluding a tiny English stopword set. Fit for the fallback path —
    anything smarter should live in the SLM.
    """
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", content)
    seen: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in _STOPWORDS or low in seen:
            continue
        seen.append(low)
        if len(seen) >= limit:
            break
    return seen


@runtime_checkable
class DecisionEngine(Protocol):
    """Async protocol. Local to this module (Phase A)."""

    async def decide(
        self, *, content: str, workspace_id: str, record_id: str
    ) -> FreshnessDecision: ...


class RuleBasedDecisionEngine:
    """Heuristic engine — confidence 0.55, keyword-extracted tags."""

    async def decide(
        self, *, content: str, workspace_id: str, record_id: str
    ) -> FreshnessDecision:
        tags = _extract_keywords(content)
        return FreshnessDecision(
            action="tag",
            confidence=0.55,
            tags=tags,
            entities=[],
            rationale="rule_based_keyword_extraction",
        )


_PROMPT = (
    "You are a memory curator. Given a memory record, return a JSON object "
    "with keys action (string), confidence (0..1 float), tags (list of "
    "lowercase strings), entities (list of proper-noun strings), and "
    "rationale (short string). Reply with JSON only — no prose."
)


def _extract_json_block(raw: str) -> str:
    """Pull the first balanced {...} block out of an LLM reply."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no json block")
    return raw[start : end + 1]


def _parse_decision(raw: str) -> FreshnessDecision:
    block = _extract_json_block(raw)
    data = json.loads(block)
    if not isinstance(data, dict):
        raise ValueError("decision is not an object")
    action = str(data.get("action") or "tag")
    confidence = float(data.get("confidence") or 0.0)
    confidence = max(0.0, min(1.0, confidence))
    tags_raw = data.get("tags") or []
    entities_raw = data.get("entities") or []
    if not isinstance(tags_raw, list) or not isinstance(entities_raw, list):
        raise ValueError("tags/entities must be lists")
    return FreshnessDecision(
        action=action,
        confidence=confidence,
        tags=[str(t) for t in tags_raw],
        entities=[str(e) for e in entities_raw],
        rationale=str(data.get("rationale") or ""),
    )


class LLMBackedDecisionEngine:
    """Engine that calls a small LLM (SLM) and falls back on failure."""

    def __init__(self, *, provider: LLMProvider, model: str) -> None:
        self._provider = provider
        self._model = model
        self._fallback = RuleBasedDecisionEngine()

    async def decide(
        self, *, content: str, workspace_id: str, record_id: str
    ) -> FreshnessDecision:
        messages = [
            Message(role="system", content=_PROMPT),
            Message(role="user", content=content[:4000]),
        ]
        try:
            response = await asyncio.to_thread(
                self._provider.chat_completion,
                messages=messages,
                temperature=0.1,
                json_mode=True,
            )
        except Exception:
            logger.warning(
                "freshness.decision.provider_failed",
                workspace_id=workspace_id,
                record_id=record_id,
                exc_info=True,
            )
            return await self._fallback.decide(
                content=content,
                workspace_id=workspace_id,
                record_id=record_id,
            )
        try:
            return _parse_decision(response.content)
        except (ValueError, KeyError, TypeError):
            logger.warning(
                "freshness.decision.parse_failed",
                workspace_id=workspace_id,
                record_id=record_id,
                raw=response.content[:200],
            )
            return await self._fallback.decide(
                content=content,
                workspace_id=workspace_id,
                record_id=record_id,
            )


def build_default_decision_engine() -> DecisionEngine:
    """Build the engine declared by ``Settings``.

    If no LLM base URL is configured, returns a ``RuleBasedDecisionEngine``.
    """
    settings = get_settings()
    if not settings.freshness_llm_api_base_url:
        return RuleBasedDecisionEngine()
    # Import locally so the dependency chain (providers → requests) does
    # not pull in at module import when the flag is off.
    from metatron.llm.provider import create_provider

    provider = create_provider(
        provider_name=settings.freshness_llm_provider or None,
        model=settings.freshness_llm_model,
        api_url=settings.freshness_llm_api_base_url,
        api_key=settings.freshness_llm_api_key,
    )
    return LLMBackedDecisionEngine(
        provider=provider,
        model=settings.freshness_llm_model,
    )


async def apply_decision(
    *,
    workspace_id: str,
    record: MemoryRecord,
    decision: FreshnessDecision,
    threshold: float,
    pg_store: MemoryPostgresStore,
    freshness_pg: FreshnessPostgresStore,
) -> dict[str, object]:
    """Apply a decision to the record or queue it for review.

    Returns a summary dict: ``{"applied": bool, "action": str, ...}``.
    """
    if decision.confidence >= threshold:
        # Merge tags idempotently one by one so the append_tag helper keeps
        # its single-shot semantics.
        for tag in decision.tags:
            await pg_store.update_lifecycle(
                workspace_id,
                record.id,
                append_tag=tag,
            )
        if decision.action == "mark_stale":
            from metatron.core.models import MemoryStatus

            await pg_store.update_lifecycle(
                workspace_id,
                record.id,
                status=MemoryStatus.STALE,
                freshness_score=0.25,
            )
        return {
            "applied": True,
            "action": decision.action,
            "confidence": decision.confidence,
            "tags": list(decision.tags),
        }

    entry = ReviewEntry(
        workspace_id=workspace_id,
        record_id=record.id,
        reason="low_confidence_decision",
        content=record.content,
        confidence=decision.confidence,
    )
    saved = await freshness_pg.save_review_entry(entry)
    return {
        "applied": False,
        "action": decision.action,
        "confidence": decision.confidence,
        "review_entry_id": saved.id,
    }
