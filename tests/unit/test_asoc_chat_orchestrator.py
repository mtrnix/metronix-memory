"""Unit tests for AsocChatOrchestrator (MTRNIX-354, T4).

Tests focus on the SSE invariants:
- done is always the last event
- error is always followed by done
- workspace_not_ready, rate_limited, visibility_filter_failed
- llm_unavailable when provider not configured
- happy-path: chunk events + done
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from metatron.auth.asoc_jwt import AsocAuthContext
from metatron.chat.asoc_orchestrator import AsocChatOrchestrator
from metatron.chat.asoc_rate_limit import InMemoryTokenBucket
from metatron.chat.models import ChatMessageRole, ChatThread
from metatron.core.config import Settings
from metatron.integrations.asoc_mcp_client import McpAuthError
from metatron.integrations.asoc_visibility import VisibilityFilterError
from metatron.llm.asoc_chat_provider import (
    AsocStreamingChatProvider,
    StreamDelta,
)
from metatron.workspaces.bootstrap.models import BootstrapStateEnum

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides: Any) -> Settings:
    base = {
        "METATRON_ENV": "development",
        "AUTH_ENABLED": "false",
        "ASOC_SHARED_SECRET": "secret",
        "ASOC_JWT_ALGORITHM": "HS256",
        "METATRON_ASOC_INSTANCE_ID": "test",
        "METATRON_CHAT_RATE_LIMIT_PER_MIN": "100",
        "METATRON_CHAT_TIMEOUT_SECONDS": "30",
        "METATRON_CHAT_MAX_TOOL_CALLS_PER_REQUEST": "8",
        "METATRON_CHAT_CONTEXT_MAX_CHARS": "24000",
    }
    base.update(overrides)
    return Settings(**base)


def _make_auth(user_id: str = "u1", project_id: str = "proj1") -> AsocAuthContext:
    return AsocAuthContext(
        user_jwt="tok",
        user_id=user_id,
        project_id=project_id,
        claims={"sub": user_id, "project_id": project_id},
        expires_at=datetime(2027, 1, 1, tzinfo=UTC),
    )


def _make_thread(workspace_id: str = "asoc-test-proj1", user_id: str = "u1") -> ChatThread:
    return ChatThread(
        thread_id=uuid4(),
        workspace_id=workspace_id,
        user_id=user_id,
        created_at=datetime.now(UTC),
        last_message_at=None,
    )


def _make_bootstrap_state(state: BootstrapStateEnum) -> Any:
    s = MagicMock()
    s.state = state
    return s


class _Body:
    """Minimal request body object."""

    def __init__(self, message: str = "hello", history: list | None = None):
        self.message = message
        self.history = history


async def _collect(gen: Any) -> list[dict[str, Any]]:
    events = []
    async for ev in gen:
        events.append(ev)
        if ev.get("event") == "done":
            break
    return events


def _make_orchestrator(
    *,
    persistence: Any = None,
    bootstrap_store: Any = None,
    visibility_filter: Any = None,
    mcp_client: Any = None,
    chat_provider: Any = None,
    rate_limiter: Any = None,
    settings: Settings | None = None,
) -> AsocChatOrchestrator:
    if persistence is None:
        persistence = AsyncMock()
        persistence.get_or_create_thread.return_value = _make_thread()
        persistence.list_messages.return_value = []
        persistence.append_message.return_value = AsyncMock(return_value=MagicMock())

    if bootstrap_store is None:
        bootstrap_store = AsyncMock()
        bootstrap_store.get.return_value = _make_bootstrap_state(BootstrapStateEnum.READY)

    if visibility_filter is None:
        visibility_filter = AsyncMock()
        visibility_filter.filter_chunks.return_value = ([], {})

    if mcp_client is None:
        mcp_client = AsyncMock()
        mcp_client.list_available_tools.return_value = []

    if chat_provider is None:
        chat_provider = MagicMock(spec=AsocStreamingChatProvider)
        chat_provider.is_available = False

    if rate_limiter is None:
        rate_limiter = AsyncMock(spec=InMemoryTokenBucket)
        rate_limiter.acquire.return_value = True

    if settings is None:
        settings = _make_settings()

    return AsocChatOrchestrator(
        persistence=persistence,
        bootstrap_store=bootstrap_store,
        asoc_visibility_filter=visibility_filter,
        asoc_mcp_client=mcp_client,
        asoc_chat_provider=chat_provider,
        rate_limiter=rate_limiter,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# done always last invariant
# ---------------------------------------------------------------------------


class TestDoneAlwaysLast:
    async def test_workspace_not_ready_done_is_last(self) -> None:
        bootstrap_store = AsyncMock()
        bootstrap_store.get.return_value = _make_bootstrap_state(
            BootstrapStateEnum.BOOTSTRAPPING
        )
        orch = _make_orchestrator(bootstrap_store=bootstrap_store)

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer", new_callable=AsyncMock
        ):
            events = await _collect(orch.run(_make_auth(), _Body(), MagicMock()))

        assert events[-1]["event"] == "done"

    async def test_workspace_none_done_is_last(self) -> None:
        bootstrap_store = AsyncMock()
        bootstrap_store.get.return_value = None
        orch = _make_orchestrator(bootstrap_store=bootstrap_store)

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer", new_callable=AsyncMock
        ):
            events = await _collect(orch.run(_make_auth(), _Body(), MagicMock()))

        assert events[-1]["event"] == "done"

    async def test_rate_limited_done_is_last(self) -> None:
        rate_limiter = AsyncMock(spec=InMemoryTokenBucket)
        rate_limiter.acquire.return_value = False
        orch = _make_orchestrator(rate_limiter=rate_limiter)

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer", new_callable=AsyncMock
        ):
            events = await _collect(orch.run(_make_auth(), _Body(), MagicMock()))

        assert events[-1]["event"] == "done"

    async def test_llm_unavailable_done_is_last(self) -> None:
        orch = _make_orchestrator()  # chat_provider.is_available = False

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=[],
        ):
            events = await _collect(orch.run(_make_auth(), _Body(), MagicMock()))

        assert events[-1]["event"] == "done"

    async def test_visibility_filter_error_done_is_last(self) -> None:
        visibility_filter = AsyncMock()
        visibility_filter.filter_chunks.side_effect = VisibilityFilterError("filter error")
        orch = _make_orchestrator(visibility_filter=visibility_filter)

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=[],
        ):
            events = await _collect(orch.run(_make_auth(), _Body(), MagicMock()))

        assert events[-1]["event"] == "done"


# ---------------------------------------------------------------------------
# error always before done
# ---------------------------------------------------------------------------


class TestErrorBeforeDone:
    async def test_workspace_not_ready_has_error_before_done(self) -> None:
        bootstrap_store = AsyncMock()
        bootstrap_store.get.return_value = _make_bootstrap_state(
            BootstrapStateEnum.BOOTSTRAPPING
        )
        orch = _make_orchestrator(bootstrap_store=bootstrap_store)

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer", new_callable=AsyncMock
        ):
            events = await _collect(orch.run(_make_auth(), _Body(), MagicMock()))

        event_types = [e["event"] for e in events]
        assert "error" in event_types
        error_idx = event_types.index("error")
        done_idx = event_types.index("done")
        assert error_idx < done_idx

    async def test_rate_limited_has_error_before_done(self) -> None:
        rate_limiter = AsyncMock(spec=InMemoryTokenBucket)
        rate_limiter.acquire.return_value = False
        orch = _make_orchestrator(rate_limiter=rate_limiter)

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer", new_callable=AsyncMock
        ):
            events = await _collect(orch.run(_make_auth(), _Body(), MagicMock()))

        codes = [json.loads(e["data"]).get("code") for e in events if e["event"] == "error"]
        assert "rate_limited" in codes


# ---------------------------------------------------------------------------
# Workspace isolation
# ---------------------------------------------------------------------------


class TestWorkspaceDerivation:
    async def test_workspace_id_derived_from_project_id(self) -> None:
        """Workspace is `asoc-{instance}-{project_id}`, not from JWT user."""
        persistence = AsyncMock()
        thread = _make_thread(workspace_id="asoc-test-proj1")
        persistence.get_or_create_thread.return_value = thread
        persistence.list_messages.return_value = []
        persistence.append_message = AsyncMock(return_value=MagicMock())

        orch = _make_orchestrator(persistence=persistence)
        auth = _make_auth(project_id="proj1")

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await _collect(orch.run(auth, _Body(), MagicMock()))

        # Workspace passed to get_or_create_thread should be asoc-test-proj1
        call_args = persistence.get_or_create_thread.call_args
        workspace_arg = call_args[0][0]
        assert workspace_arg == "asoc-test-proj1"


# ---------------------------------------------------------------------------
# MCP auth failure (non-graceful)
# ---------------------------------------------------------------------------


class TestMcpAuthFailure:
    async def test_mcp_auth_error_emits_error_and_done(self) -> None:
        mcp_client = AsyncMock()
        mcp_client.list_available_tools.side_effect = McpAuthError("JWT bad")
        orch = _make_orchestrator(mcp_client=mcp_client)

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=[],
        ):
            events = await _collect(orch.run(_make_auth(), _Body(), MagicMock()))

        event_types = [e["event"] for e in events]
        assert "error" in event_types
        assert event_types[-1] == "done"


# ---------------------------------------------------------------------------
# LLM unavailable
# ---------------------------------------------------------------------------


class TestLlmUnavailable:
    async def test_llm_not_available_emits_error(self) -> None:
        orch = _make_orchestrator()  # chat_provider.is_available = False by default

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=[],
        ):
            events = await _collect(orch.run(_make_auth(), _Body(), MagicMock()))

        codes = [json.loads(e["data"]).get("code") for e in events if e["event"] == "error"]
        assert "llm_unavailable" in codes


# ---------------------------------------------------------------------------
# Happy path: chunks stream, done is last
# ---------------------------------------------------------------------------


async def _stream_stop(*args: Any, **kwargs: Any) -> Any:
    """Async generator returning a stop finish_reason."""
    yield StreamDelta(content="Hello ")
    yield StreamDelta(content="world")
    yield StreamDelta(finish_reason="stop")


class TestHappyPath:
    async def test_chunk_events_emitted_and_done_last(self) -> None:
        persistence = AsyncMock()
        thread = _make_thread()
        persistence.get_or_create_thread.return_value = thread
        persistence.list_messages.return_value = []
        persistence.append_message = AsyncMock(return_value=MagicMock())

        chat_provider = MagicMock(spec=AsocStreamingChatProvider)
        chat_provider.is_available = True
        chat_provider.stream = _stream_stop

        orch = _make_orchestrator(persistence=persistence, chat_provider=chat_provider)

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=[],
        ):
            events = await _collect(orch.run(_make_auth(), _Body(), MagicMock()))

        chunk_events = [e for e in events if e["event"] == "chunk"]
        assert len(chunk_events) >= 1
        texts = [json.loads(e["data"])["text"] for e in chunk_events]
        assert "Hello " in texts or "world" in texts
        assert events[-1]["event"] == "done"

    async def test_user_message_persisted(self) -> None:
        persistence = AsyncMock()
        thread = _make_thread()
        persistence.get_or_create_thread.return_value = thread
        persistence.list_messages.return_value = []
        persistence.append_message = AsyncMock(return_value=MagicMock())

        chat_provider = MagicMock(spec=AsocStreamingChatProvider)
        chat_provider.is_available = True
        chat_provider.stream = _stream_stop

        orch = _make_orchestrator(persistence=persistence, chat_provider=chat_provider)

        with patch(
            "metatron.retrieval.search.hybrid_search_and_answer",
            new_callable=AsyncMock,
            return_value=[],
        ):
            await _collect(orch.run(_make_auth(), _Body(message="my question"), MagicMock()))

        # First append_message call should be for the user role with the message text
        calls = persistence.append_message.call_args_list
        user_calls = [
            c for c in calls if len(c[0]) >= 3 and c[0][2] == ChatMessageRole.USER
        ]
        assert any(c[0][3] == "my question" for c in user_calls)
