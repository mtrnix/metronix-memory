"""Shared helpers for memory MCP tools."""

from __future__ import annotations

from metatron.core.models import LifecycleStatus, MemoryScope


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
