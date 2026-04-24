"""Curator + sync_downstream_stores regression tests (MTRNIX-322).

The Curator promotes CANDIDATE → ACTIVE. MTRNIX-322 adds an explicit
``sync_downstream_stores`` call after the PG transition so the Qdrant
``status`` payload mirrors the new state. These tests pin that wiring.

We use a mocked ``FreshnessTarget`` (rather than the real ``MemoryTarget``)
to keep the assertion surface focused on whether Curator calls the hook,
regardless of adapter-specific implementation details.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from metatron.core.models import LifecycleStatus
from metatron.freshness.stages.curator import Curator
from metatron.freshness.targets import FreshnessTargetRecord


def _target_record(**overrides: object) -> FreshnessTargetRecord:
    defaults: dict[str, object] = {
        "target_id": "rec1",
        "workspace_id": "ws1",
        "content": "candidate memory",
        "tags": [],
        "status": LifecycleStatus.CANDIDATE,
        "freshness_score": 0.5,
        "superseded_by": None,
        "valid_until": None,
        "updated_at": datetime(2026, 4, 20, tzinfo=UTC),
        "evidence_count": 1,
        "verification_state": None,
        "last_freshness_run_at": None,
        "agent_id": "agent1",
    }
    defaults.update(overrides)
    return FreshnessTargetRecord(**defaults)  # type: ignore[arg-type]


def _build() -> tuple[Curator, AsyncMock, AsyncMock, AsyncMock]:
    target = AsyncMock()
    target.kind = "memory_record"
    target.supports_candidate_promotion = True
    coordination = AsyncMock()
    freshness_store = AsyncMock()
    curator = Curator(
        target=target,
        freshness_store=freshness_store,
        coordination=coordination,
    )
    return curator, target, coordination, freshness_store


async def test_promotion_calls_sync_downstream_stores() -> None:
    curator, target, coord, fs = _build()
    coord.acquire_lock.return_value = "tok"
    target.get.return_value = _target_record(freshness_score=0.8)

    result = await curator.run("ws1", "rec1")

    assert result is LifecycleStatus.ACTIVE
    target.update_lifecycle.assert_awaited_once()
    target.sync_downstream_stores.assert_awaited_once_with(
        "ws1",
        "rec1",
        status=LifecycleStatus.ACTIVE,
        freshness_score=0.8,
    )
    fs.save_machine_event.assert_awaited_once()


async def test_promotion_uses_default_score_when_record_score_missing() -> None:
    """None/0 on ``record.freshness_score`` must fall back to the 0.5 default."""
    curator, target, coord, _fs = _build()
    coord.acquire_lock.return_value = "tok"
    target.get.return_value = _target_record(freshness_score=0.0)

    await curator.run("ws1", "rec1")

    target.sync_downstream_stores.assert_awaited_once_with(
        "ws1",
        "rec1",
        status=LifecycleStatus.ACTIVE,
        freshness_score=0.5,
    )


async def test_no_transition_does_not_call_sync() -> None:
    curator, target, coord, _fs = _build()
    coord.acquire_lock.return_value = "tok"
    # Already ACTIVE — Curator short-circuits.
    target.get.return_value = _target_record(status=LifecycleStatus.ACTIVE)

    result = await curator.run("ws1", "rec1")

    assert result is None
    target.update_lifecycle.assert_not_awaited()
    target.sync_downstream_stores.assert_not_awaited()


async def test_zero_evidence_does_not_call_sync() -> None:
    curator, target, coord, _fs = _build()
    coord.acquire_lock.return_value = "tok"
    target.get.return_value = _target_record(evidence_count=0)

    result = await curator.run("ws1", "rec1")

    assert result is None
    target.update_lifecycle.assert_not_awaited()
    target.sync_downstream_stores.assert_not_awaited()


async def test_sync_downstream_failure_propagates_but_lock_released() -> None:
    """Adapter contract says the hook never raises — but Curator must tolerate
    the exceptional case where it somehow does (belt + suspenders).

    The worker hosts the ``try/finally`` for lock release; the sync call sits
    inside the ``try`` block. A raised exception propagates out of ``run``
    but the lock release still fires.
    """
    curator, target, coord, _fs = _build()
    coord.acquire_lock.return_value = "tok"
    target.get.return_value = _target_record()
    target.sync_downstream_stores.side_effect = RuntimeError("qdrant catastrophically down")

    # The adapter is supposed to swallow. If someone breaks the contract
    # and the hook does raise, Curator currently lets it propagate — but
    # the lock MUST still be released.
    raised = False
    try:
        await curator.run("ws1", "rec1")
    except RuntimeError:
        raised = True

    assert raised is True
    coord.release.assert_awaited_once()


async def test_kb_target_short_circuits_without_sync() -> None:
    curator, target, coord, _fs = _build()
    target.supports_candidate_promotion = False

    result = await curator.run("ws1", "rec1")

    assert result is None
    coord.acquire_lock.assert_not_called()
    target.sync_downstream_stores.assert_not_awaited()
