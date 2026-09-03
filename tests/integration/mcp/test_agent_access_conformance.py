"""Direct MCP conformance checks for explicit agent ownership and delegation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from metronix.activity.context import bind_agent_id, current_agent_id
from metronix.auth.policy import AuthorizationEvaluator
from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal


@dataclass(frozen=True)
class _Grant:
    workspace_id: str
    agent_id: str
    principal_user_id: str
    capability: str
    grant_type: str


class _GrantStore:
    def __init__(self, grants: list[_Grant]) -> None:
        self._grants = grants

    async def list_active_grants(
        self, workspace_id: str, agent_id: str, principal_user_id: str
    ) -> list[_Grant]:
        return [
            grant
            for grant in self._grants
            if (grant.workspace_id, grant.agent_id, grant.principal_user_id)
            == (workspace_id, agent_id, principal_user_id)
        ]


class _AuditStore:
    async def insert(self, row: object) -> None:
        return None


@contextmanager
def _transport_agent(agent_id: str) -> Iterator[None]:
    token = bind_agent_id(agent_id)
    try:
        yield
    finally:
        current_agent_id.reset(token)


@pytest.fixture
def evaluator(monkeypatch: pytest.MonkeyPatch) -> AuthorizationEvaluator:
    from metronix.mcp.tools import _agent_access

    authorizer = AuthorizationEvaluator(
        _GrantStore(
            [
                _Grant("ws-a", "owner-agent", "owner", "admin", "owner"),
                _Grant("ws-a", "shared-agent", "delegate", "read", "delegate"),
            ]
        )
    )
    monkeypatch.setattr(_agent_access, "get_authorization_evaluator", lambda: authorizer)
    monkeypatch.setattr(_agent_access, "get_agent_access_audit_store", lambda: _AuditStore())
    return authorizer


@pytest.mark.asyncio
async def test_delegated_read_can_call_search_for_the_explicitly_shared_agent(
    evaluator: AuthorizationEvaluator,
) -> None:
    from metronix.mcp.tools.memory_search import metronix_memory_search

    service = AsyncMock()
    service.search = AsyncMock(return_value=[])
    token = bind_principal(MCPPrincipal("delegate", "editor", ("ws-a",)))
    try:
        with (
            patch(
                "metronix.mcp.tools.memory_search._memory_deps.build_memory_service_for_workspace",
                new=AsyncMock(return_value=service),
            ),
            _transport_agent("shared-agent"),
        ):
            out = await metronix_memory_search(
                query="recall", workspace_id="ws-a", agent_id="shared-agent"
            )
    finally:
        reset_principal(token)

    assert out["count"] == 0
    service.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_delegated_read_cannot_write_or_swap_to_another_agent(
    evaluator: AuthorizationEvaluator,
) -> None:
    from metronix.mcp.tools.memory_search import metronix_memory_search
    from metronix.mcp.tools.memory_store import metronix_memory_store

    search_service = AsyncMock()
    store_service = AsyncMock()
    token = bind_principal(MCPPrincipal("delegate", "editor", ("ws-a",)))
    try:
        with (
            patch(
                "metronix.mcp.tools.memory_search._memory_deps.build_memory_service_for_workspace",
                new=AsyncMock(return_value=search_service),
            ) as build_search,
            patch(
                "metronix.mcp.tools.memory_store._memory_deps.build_memory_service_for_workspace",
                new=AsyncMock(return_value=store_service),
            ) as build_store,
        ):
            with _transport_agent("owner-agent"):
                swapped = await metronix_memory_search(
                    query="recall", workspace_id="ws-a", agent_id="owner-agent"
                )
            with _transport_agent("shared-agent"):
                write = await metronix_memory_store(
                    content="attempted mutation",
                    workspace_id="ws-a",
                    agent_id="shared-agent",
                )
    finally:
        reset_principal(token)

    assert swapped["error"]["code"] == "AUTH_REQUIRED"
    assert write["error"]["code"] == "AUTH_REQUIRED"
    build_search.assert_not_awaited()
    build_store.assert_not_awaited()


@pytest.mark.asyncio
async def test_review_actions_use_the_same_agent_capability_decision(
    evaluator: AuthorizationEvaluator,
) -> None:
    from metronix.mcp.tools.memory_review_list import metronix_memory_review_list
    from metronix.mcp.tools.memory_review_resolve import metronix_memory_review_resolve

    service = AsyncMock()
    token = bind_principal(MCPPrincipal("delegate", "editor", ("ws-a",)))
    try:
        with (
            patch(
                "metronix.mcp.tools.memory_review_list._memory_deps.build_memory_service_for_workspace",
                new=AsyncMock(return_value=service),
            ) as build_list,
            patch(
                "metronix.mcp.tools.memory_review_resolve._memory_deps.build_memory_service_for_workspace",
                new=AsyncMock(return_value=service),
            ) as build_resolve,
        ):
            with _transport_agent("owner-agent"):
                list_out = await metronix_memory_review_list(
                    workspace_id="ws-a", agent_id="owner-agent"
                )
            with _transport_agent("shared-agent"):
                resolve_out = await metronix_memory_review_resolve(
                    review_id="review-1",
                    action="keep",
                    workspace_id="ws-a",
                    agent_id="shared-agent",
                )
    finally:
        reset_principal(token)

    assert list_out["error"]["code"] == "AUTH_REQUIRED"
    assert resolve_out["error"]["code"] == "AUTH_REQUIRED"
    build_list.assert_not_awaited()
    build_resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_mismatched_transport_agent_is_rejected_before_access_or_storage() -> None:
    from metronix.mcp.tools.memory_store import metronix_memory_store

    access = AsyncMock()
    build_service = AsyncMock()
    principal_token = bind_principal(MCPPrincipal("owner", "editor", ("ws-a",)))
    try:
        with (
            _transport_agent("header-agent"),
            patch("metronix.mcp.tools._agent_access.require_agent_access", access),
            patch(
                "metronix.mcp.tools.memory_store._memory_deps.build_memory_service_for_workspace",
                build_service,
            ),
        ):
            result = await metronix_memory_store(
                content="must not be stored",
                workspace_id="ws-a",
                agent_id="tool-agent",
            )
    finally:
        reset_principal(principal_token)

    assert result["error"]["code"] == "INVALID_PARAMS"
    access.assert_not_awaited()
    build_service.assert_not_awaited()
