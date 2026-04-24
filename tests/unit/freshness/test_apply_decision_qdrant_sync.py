"""apply_decision + sync_downstream_stores tests (MTRNIX-322).

``apply_decision`` writes ``status=STALE`` when a high-confidence decision
has ``action="mark_stale"``. MTRNIX-322 adds a ``sync_downstream_stores``
call after that PG write so the Qdrant ``status`` payload mirrors the
new state. Tag-only branches and below-threshold branches do not mutate
``status`` and therefore do NOT call the sync hook.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from metatron.core.models import FreshnessDecision, LifecycleStatus
from metatron.freshness.apply_decision import apply_decision
from metatron.freshness.targets import FreshnessTargetRecord


def _target_record(**overrides: object) -> FreshnessTargetRecord:
    defaults: dict[str, object] = {
        "target_id": "rec1",
        "workspace_id": "ws1",
        "content": "content",
        "tags": [],
        "status": LifecycleStatus.ACTIVE,
        "freshness_score": 0.5,
        "superseded_by": None,
        "valid_until": None,
        "updated_at": datetime(2026, 4, 20, tzinfo=UTC),
        "evidence_count": 0,
        "verification_state": None,
        "last_freshness_run_at": None,
        "agent_id": "agent1",
    }
    defaults.update(overrides)
    return FreshnessTargetRecord(**defaults)  # type: ignore[arg-type]


def _mock_target() -> AsyncMock:
    target = AsyncMock()
    target.kind = "memory_record"
    return target


async def test_mark_stale_above_threshold_syncs_qdrant() -> None:
    target = _mock_target()
    fs = AsyncMock()
    record = _target_record()
    decision = FreshnessDecision(
        action="mark_stale",
        confidence=0.9,
        tags=["deprecated"],
        rationale="content obsolete",
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
    assert result["action"] == "mark_stale"
    target.update_lifecycle.assert_awaited_once()
    upd_kwargs = target.update_lifecycle.await_args.kwargs
    assert upd_kwargs["status"] is LifecycleStatus.STALE
    assert upd_kwargs["freshness_score"] == 0.25
    target.sync_downstream_stores.assert_awaited_once_with(
        "ws1",
        "rec1",
        status=LifecycleStatus.STALE,
        freshness_score=0.25,
    )


async def test_tag_only_above_threshold_does_not_sync() -> None:
    target = _mock_target()
    fs = AsyncMock()
    record = _target_record()
    decision = FreshnessDecision(
        action="tag",
        confidence=0.85,
        tags=["payment"],
        rationale="classified",
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
    target.update_lifecycle.assert_awaited_once()
    target.sync_downstream_stores.assert_not_awaited()


async def test_below_threshold_does_not_sync() -> None:
    target = _mock_target()
    fs = AsyncMock()
    fs.save_review_entry.return_value = type("R", (), {"id": "rev_1"})()
    record = _target_record()
    decision = FreshnessDecision(
        action="mark_stale",
        confidence=0.4,
        tags=["deprecated"],
        rationale="uncertain",
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
    target.update_lifecycle.assert_not_awaited()
    target.sync_downstream_stores.assert_not_awaited()
    fs.save_review_entry.assert_awaited_once()


async def test_mark_stale_swallows_sync_downstream_failure() -> None:
    """Adapter contract says the hook never raises; but if it did, the
    decision is already PG-committed and ``apply_decision`` should return
    the success summary nonetheless. In the current shape the exception
    would propagate out; this test pins the behaviour explicitly so any
    future ``try/except`` addition around the sync call is an intentional
    change with tests to update.
    """
    target = _mock_target()
    fs = AsyncMock()
    record = _target_record()
    decision = FreshnessDecision(
        action="mark_stale",
        confidence=0.95,
        tags=[],
        rationale="clear",
    )
    target.sync_downstream_stores.side_effect = RuntimeError("qdrant catastrophic")

    raised = False
    try:
        await apply_decision(
            workspace_id="ws1",
            record=record,
            decision=decision,
            threshold=0.7,
            target=target,
            freshness_store=fs,
        )
    except RuntimeError:
        raised = True

    # PG write always happens first — it's committed regardless of sync
    # outcome. The adapter is expected to swallow; if it does not, the
    # worker error handler will log + counter-bump, matching the
    # resilience behaviour elsewhere in the pipeline.
    assert raised is True
    target.update_lifecycle.assert_awaited_once()
