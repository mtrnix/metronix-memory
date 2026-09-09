"""Shared helpers for memory MCP tools."""

from __future__ import annotations

from metronix.core.models import LifecycleStatus, MemoryKind, MemoryScope


def scope_from_str(scope: str) -> MemoryScope:
    """Convert a required ``scope`` string to ``MemoryScope``.

    Raises ``ValueError`` when the value does not match a known scope.
    """
    try:
        return MemoryScope(scope)
    except ValueError as exc:
        valid = ", ".join(s.value for s in MemoryScope)
        raise ValueError(f"invalid scope {scope!r}; valid: {valid}") from exc


def scope_from_str_optional(scope: str | None) -> MemoryScope | None:
    """Convert an optional ``scope`` string to ``MemoryScope``.

    Returns ``None`` when ``scope`` is ``None`` or empty.
    Raises ``ValueError`` when a non-empty value does not match a known scope.
    """
    if not scope:
        return None
    return scope_from_str(scope)


def parse_status_filter(
    status: list[str] | None,
) -> list[LifecycleStatus] | None:
    """Convert an MCP ``status`` parameter into a ``LifecycleStatus`` list.

    MTRNIX-314. Semantics:
    * ``None`` (not supplied) -> ``[LifecycleStatus.ACTIVE]`` (default filter).
    * ``["all"]`` -> ``None`` (disables the filter at every layer).
    * Otherwise every entry is parsed as a ``LifecycleStatus``; invalid
      values raise ``ValueError`` with a hint listing valid values.
    """
    if status is None:
        return [LifecycleStatus.ACTIVE]
    if len(status) == 1 and status[0] == "all":
        return None
    out: list[LifecycleStatus] = []
    for s in status:
        try:
            out.append(LifecycleStatus(s))
        except ValueError as exc:
            valid = [v.value for v in LifecycleStatus] + ["all"]
            msg = f"invalid status '{s}'; valid values: {valid}"
            raise ValueError(msg) from exc
    return out


def validate_importance_score(value: float) -> float:
    """Coerce ``importance_score`` to a float inside the documented 0.0..1.0 range.

    Raises ``ValueError`` when the value is not numeric, is not finite, or falls
    outside the range. ``importance_score`` is read back as ``graph_score`` in
    ``MemorySearchService.hybrid_search`` and multiplied into the ranking sum, so
    an out-of-range score does not fail loudly — it silently dominates ranking.
    The REST surface already enforces this bound through its Pydantic field
    (``Field(0.5, ge=0.0, le=1.0)``); this keeps the MCP tools on the same
    contract.
    """
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        msg = f"importance_score must be a number, got {value!r}"
        raise ValueError(msg) from exc
    # Rejects NaN as a side effect: every comparison against NaN is False.
    if not 0.0 <= score <= 1.0:
        msg = f"importance_score must be between 0.0 and 1.0, got {score}"
        raise ValueError(msg)
    return score


def validate_kind(kind: str | None) -> MemoryKind | None:
    """Convert an optional kind string to ``MemoryKind``.

    Returns ``None`` when ``kind`` is ``None``.
    Raises ``ValueError`` when a non-None value does not match a known kind.
    """
    if kind is None:
        return None
    try:
        return MemoryKind(kind.lower())
    except ValueError as exc:
        valid = ", ".join(k.value for k in MemoryKind)
        msg = f"Invalid kind '{kind}'. Must be: {valid}"
        raise ValueError(msg) from exc


def validate_kind_list(
    kinds: list[str] | None,
) -> list[MemoryKind] | None:
    """Convert an optional kind list to ``list[MemoryKind]``.

    Returns ``None`` when ``kinds`` is ``None`` or empty.
    Raises ``ValueError`` when any value does not match a known kind.
    """
    if not kinds:
        return None
    return [validate_kind(k) for k in kinds]  # type: ignore[misc]
