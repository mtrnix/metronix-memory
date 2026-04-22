"""Apply a DecisionEngine output to a target (MTRNIX-313).

Extracted from :mod:`metatron.freshness.decision_engine` (Phase A) so it can
take a :class:`FreshnessTarget` instead of a concrete memory PG store —
memory and KB pipelines now share one implementation.

Behaviour:

* ``decision.confidence >= threshold`` → apply side-effects via the target
  (tag append, optional STALE transition). Returns ``{"applied": True, ...}``.
* Below threshold  → create a ``ReviewEntry(reason="low_confidence_decision")``
  in the shared ``FreshnessStore``. Returns ``{"applied": False, ...}``.

Tags are passed to the target via ``append_tag=`` so the memory adapter can
do one SQL-side array merge per invocation; the KB adapter ignores the kwarg
(raw_documents has no tags column in Phase B).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from metatron.core.models import LifecycleStatus, ReviewEntry

if TYPE_CHECKING:
    from metatron.core.models import FreshnessDecision
    from metatron.freshness.targets import FreshnessTarget, FreshnessTargetRecord
    from metatron.storage.freshness_pg import FreshnessStore

logger = structlog.get_logger()


async def apply_decision(
    *,
    workspace_id: str,
    record: FreshnessTargetRecord,
    decision: FreshnessDecision,
    threshold: float,
    target: FreshnessTarget,
    freshness_store: FreshnessStore,
) -> dict[str, object]:
    """Apply a decision to the target or queue it for review.

    Returns a summary dict: ``{"applied": bool, "action": str, ...}``.
    """
    if decision.confidence >= threshold:
        tag_list = list(decision.tags) if decision.tags else None
        # Join tags into one append_tag payload; the adapter decides how to
        # merge. The memory adapter SQL-side unions the array; the KB adapter
        # ignores tags entirely (no tags column in Phase B).
        joined_tag = ",".join(tag_list) if tag_list else None
        if decision.action == "mark_stale":
            await target.update_lifecycle(
                workspace_id,
                record.target_id,
                status=LifecycleStatus.STALE,
                freshness_score=0.25,
                append_tag=joined_tag,
            )
        elif joined_tag is not None:
            await target.update_lifecycle(
                workspace_id,
                record.target_id,
                append_tag=joined_tag,
            )
        return {
            "applied": True,
            "action": decision.action,
            "confidence": decision.confidence,
            "tags": list(decision.tags),
        }

    entry = ReviewEntry(
        workspace_id=workspace_id,
        target_id=record.target_id,
        target_kind=target.kind,
        reason="low_confidence_decision",
        content=record.content,
        confidence=decision.confidence,
    )
    saved = await freshness_store.save_review_entry(entry)
    return {
        "applied": False,
        "action": decision.action,
        "confidence": decision.confidence,
        "review_entry_id": saved.id,
    }
