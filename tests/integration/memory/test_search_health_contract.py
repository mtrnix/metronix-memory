"""Real search -> service -> REST / registered MCP tool, with storage faults.

These deterministic integration tests require no running backend services.
MCP dispatch is in-process, not an HTTP transport test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from mcp.types import CallToolResult

from metronix.activity.context import bind_agent_id, current_agent_id
from metronix.api.routes.memory import router
from metronix.auth.dependencies import get_current_user
from metronix.auth.policy import AuthorizationDecision, AuthorizationRequest
from metronix.core.config import Settings
from metronix.core.models import MemoryRecord, Role, User
from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal
from metronix.mcp.server import mcp
from metronix.mcp.tools import _agent_access
from metronix.memory.assembler import AgentContextAssembler
from metronix.memory.search import MemorySearchService, MemorySearchWeights
from metronix.memory.service import MemoryService

pytestmark = pytest.mark.integration


@dataclass
class Harness:
    app: FastAPI
    workspace: str
    qdrant: MagicMock
    redis: MagicMock
    graph: MagicMock
    allow: bool = True

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision:
        allowed = (
            self.allow and request.workspace_id == self.workspace and request.agent_id == "agent1"
        )
        return AuthorizationDecision(
            "health-test", allowed, "owner_grant" if allowed else "denied"
        )

    async def call(self, transport: str, **overrides: Any) -> tuple[int, dict[str, Any]]:
        arguments = {"query": "known", "agent_id": "agent1", **overrides}
        workspace = arguments.pop("workspace_id", self.workspace)
        if transport == "rest":
            async with AsyncClient(
                transport=ASGITransport(app=self.app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/memory/search",
                    params={"workspace_id": workspace},
                    json=arguments,
                )
            return response.status_code, response.json()
        token = bind_principal(MCPPrincipal("user1", "editor", (self.workspace,)))
        agent_token = bind_agent_id("agent1")
        try:
            result = await mcp.call_tool(
                "metronix_memory_search",
                {**arguments, "workspace_id": workspace},
            )
        finally:
            current_agent_id.reset(agent_token)
            reset_principal(token)
        assert isinstance(result, CallToolResult)
        assert result.structured_content is not None
        return 200, result.structured_content


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    workspace = f"health-{uuid4().hex[:12]}"
    qdrant = MagicMock(search=AsyncMock(return_value=[]))
    redis = MagicMock(list=AsyncMock(return_value=[]))
    graph = MagicMock(return_value=[])
    search = MemorySearchService(qdrant, redis, weights=MemorySearchWeights())
    service = MemoryService(redis, qdrant, AsyncMock(), workspace_id=workspace, search=search)
    app = FastAPI()
    app.state.settings = Settings(AUTH_ENABLED=False, METRONIX_SECRET_KEY="test-health-key")
    app.include_router(router, prefix="/api/v1")
    user = User(
        id="user1",
        username="health",
        email="test@example.com",
        role=Role.EDITOR,
        workspace_ids=[workspace],
    )
    app.dependency_overrides[get_current_user] = lambda: user

    @app.middleware("http")
    async def principal(request: Request, call_next):
        request.state.user = {"id": user.id, "role": "editor", "workspace_ids": [workspace]}
        request.state.workspace_id = workspace
        return await call_next(request)

    result = Harness(app, workspace, qdrant, redis, graph)
    monkeypatch.setattr("metronix.memory.search.get_agent_memories", graph)
    monkeypatch.setattr("metronix.api.routes.memory.get_memory_service", lambda request: service)
    monkeypatch.setattr("metronix.api.routes.memory.get_authorization_evaluator", lambda: result)
    monkeypatch.setattr(_agent_access, "get_authorization_evaluator", lambda: result)
    monkeypatch.setattr(_agent_access, "get_agent_access_audit_store", AsyncMock)
    monkeypatch.setattr(
        "metronix.mcp.tools._memory_deps.build_memory_service_for_workspace",
        AsyncMock(return_value=service),
    )
    return result


@pytest.mark.parametrize("transport", ["rest", "mcp"])
@pytest.mark.parametrize("case", ["empty", "outage", "surviving", "all_failed", "healthy_hits"])
async def test_public_search_health(harness: Harness, transport: str, case: str) -> None:
    args: dict[str, Any] = {}
    if case in {"outage", "surviving", "all_failed"}:
        harness.qdrant.search.side_effect = OSError("private-host fake-secret")
        harness.graph.return_value = [{"id": "known-hit", "agent_id": "agent1"}]
    if case == "all_failed":
        args["session_id"] = "session1"
        harness.graph.side_effect = TimeoutError("private-host fake-secret")
        harness.redis.list.side_effect = OSError("private-host fake-secret")
    if case == "surviving":
        args["session_id"] = "session1"
        harness.redis.list.return_value = [
            MemoryRecord(
                id="known-hit",
                workspace_id=harness.workspace,
                agent_id="agent1",
                content="known content",
            )
        ]
    if case == "healthy_hits":
        harness.qdrant.search.return_value = [
            {
                "record_id": "known-hit",
                "content": "known content",
                "score": 0.8,
                "payload": {"workspace_id": harness.workspace, "agent_id": "agent1"},
            }
        ]
        harness.graph.return_value = [{"id": "known-hit", "importance_score": 0.5}]
    status, body = await harness.call(transport, **args)
    assert status == 200
    assert "error" not in body
    assert body["partial"] is (case in {"outage", "surviving", "all_failed"})
    assert (
        body["count"]
        == len(body["results"])
        == (1 if case in {"surviving", "healthy_hits"} else 0)
    )
    if body["results"]:
        item = body["results"][0]
        assert item["record"]["id"] == "known-hit"
        assert item["record"]["content"] == "known content"
        assert item["rank"] == 1
    legs = body["legs"]
    assert legs["qdrant"]["status"] == ("failed" if body["partial"] else "ok")
    assert legs["session"]["status"] == (
        "failed" if case == "all_failed" else "ok" if case == "surviving" else "skipped"
    )
    assert legs["graph"]["status"] == ("failed" if case == "all_failed" else "ok")
    hydration = legs["graph"]["hydration"]
    assert hydration["status"] == (
        "not_attempted" if case == "all_failed" else "unavailable" if case == "outage" else "ok"
    )
    assert hydration["unavailable"] == (1 if case == "outage" else 0)
    assert (
        hydration["retrieved"]
        == hydration["resolved"] + hydration["unavailable"] + hydration["invalid"]
    )
    assert "private-host" not in json.dumps(body)
    assert "fake-secret" not in json.dumps(body)
    excluded = harness.qdrant.search.await_args.kwargs["status_exclude"]
    assert "archived" in excluded and "superseded" in excluded
    assert ("candidate" in excluded) is (transport == "mcp")


@pytest.mark.parametrize("transport", ["rest", "mcp"])
@pytest.mark.parametrize("denial", ["ungranted_agent", "cross_workspace", "policy_denied"])
async def test_denial_precedes_retrieval(harness: Harness, transport: str, denial: str) -> None:
    args = {}
    if denial == "ungranted_agent":
        args["agent_id"] = "another-agent"
    elif denial == "cross_workspace":
        args["workspace_id"] = "other-workspace"
    else:
        harness.allow = False
    status, body = await harness.call(transport, **args)
    assert status == 403 if transport == "rest" else "error" in body
    assert "legs" not in body and "partial" not in body
    harness.qdrant.search.assert_not_called()
    harness.redis.list.assert_not_called()
    harness.graph.assert_not_called()


@pytest.mark.parametrize("transport", ["rest", "mcp"])
@pytest.mark.parametrize("query", ["", " \n\t"])
async def test_blank_query_is_validation_error(
    harness: Harness, transport: str, query: str
) -> None:
    status, body = await harness.call(transport, query=query)
    if transport == "rest":
        assert status == 422
    else:
        assert body["error"]["code"] == "INVALID_PARAMS"
    harness.qdrant.search.assert_not_called()


@pytest.mark.parametrize("transport", ["rest", "mcp"])
@pytest.mark.parametrize("session_id", [None, "session1"])
@pytest.mark.parametrize("has_hit", [False, True])
async def test_healthy_graph_hydration_misses_are_informational(
    harness: Harness, transport: str, session_id: str | None, has_hit: bool
) -> None:
    if has_hit:
        harness.qdrant.search.return_value = [
            {
                "record_id": "known-hit",
                "content": "known content",
                "score": 0.8,
                "payload": {"workspace_id": harness.workspace, "agent_id": "agent1"},
            }
        ]
    harness.graph.return_value = [
        {"id": "known-hit"},
        {"id": "other-b"},
        {"id": "other-c"},
    ]
    status, body = await harness.call(transport, session_id=session_id)
    assert status == 200
    assert body["partial"] is False
    assert body["count"] == int(has_hit)
    assert body["legs"]["qdrant"]["status"] == "ok"
    assert body["legs"]["graph"]["status"] == "ok"
    assert body["legs"]["session"]["status"] == ("ok" if session_id else "skipped")
    assert body["legs"]["graph"]["hydration"] == {
        "status": "partial" if has_hit else "unavailable",
        "retrieved": 3,
        "resolved": int(has_hit),
        "unavailable": 3 - int(has_hit),
        "invalid": 0,
    }


@pytest.mark.parametrize("query", ["", " \n\t"])
async def test_blank_rewritten_query_skips_memories_without_degradation(
    harness: Harness, query: str
) -> None:
    search = MemorySearchService(harness.qdrant, harness.redis, weights=MemorySearchWeights())
    preferences = AsyncMock(
        list_preferences=AsyncMock(
            return_value=[
                MemoryRecord(content="Prefer concise answers", agent_id="agent1"),
            ]
        )
    )
    assembler = AgentContextAssembler(
        preferences,
        search,
        Settings(proxy_query_rewrite_enabled=False),
    )
    context = await assembler.assemble("agent1", harness.workspace, user_message=query)
    assert context.memories_count == 0
    assert context.sections["relevant_memories"] == ""
    assert context.degraded_sections == []
    assert context.preferences_count == 1
    assert "Prefer concise answers" in context.system_prompt
    harness.qdrant.search.assert_not_called()
    harness.graph.assert_not_called()
    harness.redis.list.assert_not_called()
