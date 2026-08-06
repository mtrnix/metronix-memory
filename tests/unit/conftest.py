"""Unit-test-level fixtures."""

from __future__ import annotations

import pytest

_AGENT_MEMORY_TOOL_TEST_FILES = {
    "test_mcp_memory_tools.py",
    "test_memory_batch_store.py",
    "test_memory_context_mcp.py",
    "test_memory_list.py",
    "test_memory_list_status_filter.py",
    "test_memory_search_status_filter.py",
    "test_memory_update.py",
    "test_memory_review_list.py",
    "test_memory_review_resolve.py",
}


@pytest.fixture(autouse=True)
def allow_authenticated_agent_memory_tools(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> object:
    """Model an authenticated, explicitly allowed caller in tool unit tests."""
    if (
        request.node.path.name not in _AGENT_MEMORY_TOOL_TEST_FILES
        or request.node.get_closest_marker("no_agent_principal") is not None
    ):
        yield
        return

    from metronix.activity.context import bind_agent_id, current_agent_id
    from metronix.auth.policy import AuthorizationDecision
    from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal
    from metronix.mcp.tools import _agent_access

    class AllowingEvaluator:
        async def authorize(self, *args: object) -> AuthorizationDecision:
            return AuthorizationDecision("test-decision", True, "owner_grant")

    class AuditStore:
        async def insert(self, row: object) -> None:
            return None

    monkeypatch.setattr(_agent_access, "get_authorization_evaluator", lambda: AllowingEvaluator())
    monkeypatch.setattr(_agent_access, "get_agent_access_audit_store", lambda: AuditStore())
    token = bind_principal(MCPPrincipal("u1", "editor", ("*",)))
    agent_token = bind_agent_id("agent-a")
    try:
        yield
    finally:
        current_agent_id.reset(agent_token)
        reset_principal(token)


@pytest.fixture(autouse=True)
def clear_lru_caches() -> None:
    """Clear module-level LRU caches between tests to prevent cross-test contamination."""
    from metronix.retrieval.channels import _cached_get_graph_entities

    _cached_get_graph_entities.cache_clear()
