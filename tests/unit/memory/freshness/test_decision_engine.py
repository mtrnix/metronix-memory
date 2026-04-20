"""Unit tests for DecisionEngine (MTRNIX-304)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.models import (
    FreshnessDecision,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
)
from metatron.llm.base import LLMResponse
from metatron.memory.freshness.decision_engine import (
    LLMBackedDecisionEngine,
    RuleBasedDecisionEngine,
    apply_decision,
)


def _record(**overrides: object) -> MemoryRecord:
    defaults = {
        "id": "rec1",
        "workspace_id": "ws1",
        "agent_id": "agent1",
        "scope": MemoryScope.PER_AGENT,
        "content": "Payment integration uses Stripe webhook.",
        "status": MemoryStatus.CANDIDATE,
        "created_at": datetime(2026, 4, 20, tzinfo=UTC),
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


# ---------------------------------------------------------------------------
# RuleBasedDecisionEngine
# ---------------------------------------------------------------------------


class TestRuleBased:
    async def test_decide_returns_confidence_and_tags(self) -> None:
        engine = RuleBasedDecisionEngine()
        decision = await engine.decide(
            content="Stripe payment webhook integration details",
            workspace_id="ws1",
            record_id="rec1",
        )
        assert isinstance(decision, FreshnessDecision)
        assert decision.action == "tag"
        assert 0.5 <= decision.confidence <= 0.6
        assert decision.tags  # non-empty keyword list


# ---------------------------------------------------------------------------
# LLMBackedDecisionEngine
# ---------------------------------------------------------------------------


class TestLLMBacked:
    async def test_parses_valid_json_response(self) -> None:
        provider = MagicMock()
        provider.chat_completion.return_value = LLMResponse(
            content=(
                '{"action":"tag","confidence":0.82,'
                '"tags":["payment","stripe"],'
                '"entities":["Stripe"],'
                '"rationale":"extracted from content"}'
            ),
            model="qwen",
            provider="stub",
        )
        engine = LLMBackedDecisionEngine(provider=provider, model="qwen")

        decision = await engine.decide(
            content="Stripe payment webhook",
            workspace_id="ws1",
            record_id="rec1",
        )

        assert decision.action == "tag"
        assert decision.confidence == 0.82
        assert decision.tags == ["payment", "stripe"]
        assert decision.entities == ["Stripe"]

    async def test_malformed_json_falls_back_to_rule_based(self) -> None:
        provider = MagicMock()
        provider.chat_completion.return_value = LLMResponse(
            content="not valid json at all",
            model="qwen",
            provider="stub",
        )
        engine = LLMBackedDecisionEngine(provider=provider, model="qwen")

        decision = await engine.decide(
            content="fallback content",
            workspace_id="ws1",
            record_id="rec1",
        )

        # Fallback engine yields confidence=0.55.
        assert 0.5 <= decision.confidence <= 0.6

    async def test_provider_exception_falls_back_to_rule_based(self) -> None:
        provider = MagicMock()
        provider.chat_completion.side_effect = RuntimeError("slm down")
        engine = LLMBackedDecisionEngine(provider=provider, model="qwen")

        decision = await engine.decide(
            content="xxx",
            workspace_id="ws1",
            record_id="rec1",
        )

        assert 0.5 <= decision.confidence <= 0.6


# ---------------------------------------------------------------------------
# apply_decision
# ---------------------------------------------------------------------------


class TestApplyDecision:
    async def test_high_confidence_applies_tag(self) -> None:
        pg = MagicMock()
        pg.update_lifecycle = AsyncMock()
        fp = AsyncMock()
        record = _record()
        decision = FreshnessDecision(
            action="tag",
            confidence=0.85,
            tags=["payment"],
            rationale="ok",
        )

        result = await apply_decision(
            workspace_id="ws1",
            record=record,
            decision=decision,
            threshold=0.7,
            pg_store=pg,
            freshness_pg=fp,
        )

        assert result["applied"] is True
        pg.update_lifecycle.assert_awaited()
        fp.save_review_entry.assert_not_awaited()

    async def test_low_confidence_creates_review_entry(self) -> None:
        pg = MagicMock()
        pg.update_lifecycle = AsyncMock()
        fp = AsyncMock()
        record = _record()
        decision = FreshnessDecision(
            action="tag",
            confidence=0.5,
            tags=["payment"],
            rationale="unsure",
        )

        result = await apply_decision(
            workspace_id="ws1",
            record=record,
            decision=decision,
            threshold=0.7,
            pg_store=pg,
            freshness_pg=fp,
        )

        assert result["applied"] is False
        fp.save_review_entry.assert_awaited_once()
        saved_entry = fp.save_review_entry.await_args.args[0]
        assert saved_entry.reason == "low_confidence_decision"
        assert saved_entry.confidence == pytest.approx(0.5)
        pg.update_lifecycle.assert_not_awaited()
