"""Shared helpers for memory MCP tools."""

from __future__ import annotations

from metatron.core.models import MemoryScope


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
