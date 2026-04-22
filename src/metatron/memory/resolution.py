"""Memory review-resolution shapes (MTRNIX-314).

Tiny module so the dataclass + action parser can be imported by MCP tools
without pulling in the full ``MemoryService``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewResolution:
    """Outcome of ``MemoryService.resolve_review``.

    Fields mirror the ``MemoryReviewResolveResponse`` MCP model so callers can
    convert straight through. ``superseded_by`` is only set for
    ``action="merge_into"`` — every other action leaves it ``None``.
    """

    review_id: str
    target_id: str
    action: str
    old_status: str
    new_status: str
    superseded_by: str | None
    machine_event_id: str


def parse_action(action: str) -> tuple[str, str | None]:
    """Parse a review action string into (action_kind, merge_target).

    Accepted forms:
    * ``keep`` / ``archive`` / ``discard`` -> (kind, None)
    * ``merge_into:<record_id>`` -> (``"merge_into"``, record_id)

    Raises ``ValueError`` on malformed input.
    """
    if action in ("keep", "archive", "discard"):
        return action, None
    if action.startswith("merge_into:"):
        target = action.removeprefix("merge_into:").strip()
        if not target:
            raise ValueError("merge_into: requires a target record id")
        return "merge_into", target
    raise ValueError(f"Unknown action: {action}")
