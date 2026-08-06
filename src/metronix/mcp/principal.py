"""Request-scoped MCP authentication principal."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class MCPPrincipal:
    """Server-derived identity for an authenticated MCP request."""

    user_id: str
    role: str
    workspace_ids: tuple[str, ...]
    auth_method: str = "jwt"


_current_principal: ContextVar[MCPPrincipal | None] = ContextVar(
    "current_mcp_principal", default=None
)


def bind_principal(principal: MCPPrincipal) -> Token[MCPPrincipal | None]:
    """Bind a principal to the current request context."""
    return _current_principal.set(principal)


def get_current_principal() -> MCPPrincipal | None:
    """Return the principal bound to the current request context, if any."""
    return _current_principal.get()


def reset_principal(token: Token[MCPPrincipal | None]) -> None:
    """Restore the principal context to its state before ``bind_principal``."""
    _current_principal.reset(token)
