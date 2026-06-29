"""Unit tests for DecisionEngine (MTRNIX-304)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from metronix.core.config import get_settings
from metronix.core.models import (
    FreshnessDecision,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
)
from metronix.freshness.targets import FreshnessTargetRecord
from metronix.llm.base import LLMResponse
from metronix.memory.freshness.decision_engine import (
    LLMBackedDecisionEngine,
    RuleBasedDecisionEngine,
    apply_decision,
    build_default_decision_engine,
)
from metronix.memory.freshness.target_memory import MemoryTarget


def _target_record(record: MemoryRecord) -> FreshnessTargetRecord:
    return FreshnessTargetRecord(
        target_id=record.id,
        workspace_id=record.workspace_id,
        content=record.content,
        status=record.status,
        freshness_score=record.freshness_score,
    )


def _build_memory_target_and_pg() -> tuple[MemoryTarget, MagicMock]:
    pg = MagicMock()
    pg.update_lifecycle = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda _ws: MagicMock())
    return target, pg


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
        target, pg = _build_memory_target_and_pg()
        fs = AsyncMock()
        record = _target_record(_record())
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
            target=target,
            freshness_store=fs,
        )

        assert result["applied"] is True
        pg.update_lifecycle.assert_awaited()
        fs.save_review_entry.assert_not_awaited()

    async def test_tag_batch_uses_single_update_call(self) -> None:
        """5 tags from the decision must merge in ONE update_lifecycle call.

        Phase B routes tags through ``MemoryTarget.update_lifecycle`` with
        ``append_tag`` carrying a comma-joined payload; the adapter unpacks
        it into ``append_tags`` so MemoryPostgresStore still does one
        SQL-side union. The invariant is: one ``pg.update_lifecycle`` call
        per decision, regardless of how many tags.
        """
        target, pg = _build_memory_target_and_pg()
        fs = AsyncMock()
        record = _target_record(_record())
        decision = FreshnessDecision(
            action="tag",
            confidence=0.9,
            tags=["payment", "stripe", "webhook", "integration", "api"],
            rationale="batched",
        )

        result = await apply_decision(
            workspace_id="ws1",
            record=record,
            decision=decision,
            threshold=0.7,
            target=target,
            freshness_store=fs,
        )

        assert result["applied"] is True
        # Exactly one UPDATE for the whole tag batch.
        assert pg.update_lifecycle.await_count == 1
        kwargs = pg.update_lifecycle.await_args.kwargs
        assert kwargs["append_tags"] == [
            "payment",
            "stripe",
            "webhook",
            "integration",
            "api",
        ]

    async def test_low_confidence_creates_review_entry(self) -> None:
        target, pg = _build_memory_target_and_pg()
        fs = AsyncMock()
        record = _target_record(_record())
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
            target=target,
            freshness_store=fs,
        )

        assert result["applied"] is False
        fs.save_review_entry.assert_awaited_once()
        saved_entry = fs.save_review_entry.await_args.args[0]
        assert saved_entry.reason == "low_confidence_decision"
        assert saved_entry.confidence == pytest.approx(0.5)
        assert saved_entry.target_kind == "memory_record"
        pg.update_lifecycle.assert_not_awaited()


# ---------------------------------------------------------------------------
# build_default_decision_engine — provider DI
# ---------------------------------------------------------------------------


class TestBuildDefaultDecisionEngine:
    async def test_base_url_without_provider_routes_to_custom(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When FRESHNESS_LLM_API_BASE_URL is set but FRESHNESS_LLM_PROVIDER
        is empty, we must route to ``CustomProvider`` — only Custom reads
        ``api_url`` from kwargs. Other providers would silently drop the URL.
        """
        settings = get_settings()
        monkeypatch.setattr(settings, "freshness_llm_api_base_url", "http://mock:11434/v1")
        monkeypatch.setattr(settings, "freshness_llm_provider", "")
        monkeypatch.setattr(settings, "freshness_llm_model", "qwen2.5-4b")
        monkeypatch.setattr(settings, "freshness_llm_api_key", "")

        captured: dict[str, object] = {}

        def fake_create_provider(**kwargs: object) -> object:
            captured.update(kwargs)
            stub = MagicMock()
            stub.api_url = str(kwargs.get("api_url", ""))
            return stub

        # Patch where ``build_default_decision_engine`` imports it from.
        import metronix.llm.provider as provider_mod

        monkeypatch.setattr(provider_mod, "create_provider", fake_create_provider)

        engine = build_default_decision_engine()

        assert isinstance(engine, LLMBackedDecisionEngine)
        assert captured["provider_name"] == "custom"
        assert captured["api_url"] == "http://mock:11434/v1"
