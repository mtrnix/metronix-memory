"""Tests for MCP action mode: action_store, action_planner, action_executor, router integration."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.mcp.action_store import ActionStore, PendingAction

# ---------------------------------------------------------------------------
# ActionStore tests
# ---------------------------------------------------------------------------


class TestActionStore:
    """Tests for in-memory action store with TTL."""

    def test_add_and_retrieve(self) -> None:
        store = ActionStore()
        action = PendingAction(
            user_id="u1", server_name="srv", tool_name="create_issue",
            arguments={"title": "Bug"}, description="Create issue",
            preview="Title: Bug",
        )
        store.add(action)
        retrieved = store.get_for_user("u1")
        assert retrieved is not None
        assert retrieved.action_id == action.action_id
        assert retrieved.tool_name == "create_issue"

    def test_get_for_user_returns_most_recent(self) -> None:
        store = ActionStore()
        a1 = PendingAction(
            user_id="u1", server_name="srv", tool_name="tool_a",
            arguments={}, description="First", preview="",
        )
        a2 = PendingAction(
            user_id="u1", server_name="srv", tool_name="tool_b",
            arguments={}, description="Second", preview="",
        )
        store.add(a1)
        store.add(a2)
        retrieved = store.get_for_user("u1")
        assert retrieved is not None
        assert retrieved.tool_name == "tool_b"

    def test_expired_action_not_returned(self) -> None:
        store = ActionStore()
        action = PendingAction(
            user_id="u1", server_name="srv", tool_name="tool",
            arguments={}, description="Old", preview="",
            ttl_seconds=0,  # expires immediately
        )
        action.created_at = time.time() - 10  # created 10s ago
        store._pending[action.action_id] = action
        assert store.get_for_user("u1") is None

    def test_remove_action(self) -> None:
        store = ActionStore()
        action = PendingAction(
            user_id="u1", server_name="srv", tool_name="tool",
            arguments={}, description="Test", preview="",
        )
        store.add(action)
        removed = store.remove(action.action_id)
        assert removed is not None
        assert removed.action_id == action.action_id
        assert store.get_for_user("u1") is None

    def test_cleanup_expired_on_access(self) -> None:
        store = ActionStore()
        expired = PendingAction(
            user_id="u1", server_name="srv", tool_name="old",
            arguments={}, description="Expired", preview="",
            ttl_seconds=0,
        )
        expired.created_at = time.time() - 100
        store._pending[expired.action_id] = expired

        fresh = PendingAction(
            user_id="u2", server_name="srv", tool_name="new",
            arguments={}, description="Fresh", preview="",
        )
        store.add(fresh)

        # Expired should be cleaned up
        assert expired.action_id not in store._pending
        assert fresh.action_id in store._pending


class TestPendingAction:
    """Tests for PendingAction model."""

    def test_expired_property(self) -> None:
        action = PendingAction(
            user_id="u1", server_name="srv", tool_name="tool",
            arguments={}, description="Test", preview="", ttl_seconds=300,
        )
        assert action.expired is False

        action.created_at = time.time() - 400
        assert action.expired is True

    def test_unique_action_id(self) -> None:
        a1 = PendingAction(
            user_id="u1", server_name="srv", tool_name="tool",
            arguments={}, description="Test", preview="",
        )
        a2 = PendingAction(
            user_id="u1", server_name="srv", tool_name="tool",
            arguments={}, description="Test", preview="",
        )
        assert a1.action_id != a2.action_id


# ---------------------------------------------------------------------------
# ActionPlanner tests
# ---------------------------------------------------------------------------


class TestActionPlanner:
    """Tests for LLM-based action planning."""

    def test_format_tools_description(self) -> None:
        from metatron.mcp.action_planner import ActionPlanner

        planner = ActionPlanner.__new__(ActionPlanner)
        tools = [
            {
                "server": "jira-mcp",
                "tool": "create_issue",
                "description": "Create a Jira issue",
                "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}}},
            },
        ]
        result = planner._format_tools_description(tools)
        assert "jira-mcp" in result
        assert "create_issue" in result
        assert "Create a Jira issue" in result

    @patch("metatron.llm.chat_completion")
    def test_plan_returns_tool_selection(self, mock_llm: MagicMock) -> None:
        from metatron.mcp.action_planner import ActionPlanner

        mock_llm.return_value = '{"server": "jira", "tool": "create_issue", "arguments": {"title": "Bug"}, "description": "Create bug", "preview": "Title: Bug"}'

        planner = ActionPlanner.__new__(ActionPlanner)
        planner._registry = MagicMock()

        tools = [{"server": "jira", "tool": "create_issue", "description": "Create issue", "inputSchema": {}}]
        result = planner.plan("Create a bug about sync failure", tools)

        assert result["server"] == "jira"
        assert result["tool"] == "create_issue"
        assert result["arguments"]["title"] == "Bug"

    def test_plan_returns_error_when_no_tools(self) -> None:
        from metatron.mcp.action_planner import ActionPlanner

        planner = ActionPlanner.__new__(ActionPlanner)
        planner._registry = MagicMock()

        result = planner.plan("Create a bug", write_tools=[])
        assert "error" in result
        assert "No write tools" in result["error"]

    @patch("metatron.llm.chat_completion")
    def test_plan_handles_malformed_llm_response(self, mock_llm: MagicMock) -> None:
        from metatron.mcp.action_planner import ActionPlanner

        mock_llm.return_value = "This is not valid JSON at all"

        planner = ActionPlanner.__new__(ActionPlanner)
        planner._registry = MagicMock()

        tools = [{"server": "srv", "tool": "tool", "description": "desc", "inputSchema": {}}]
        result = planner.plan("do something", tools)
        assert "error" in result

    @patch("metatron.llm.chat_completion")
    def test_plan_strips_markdown_code_fences(self, mock_llm: MagicMock) -> None:
        from metatron.mcp.action_planner import ActionPlanner

        mock_llm.return_value = '```json\n{"server": "srv", "tool": "t", "arguments": {}, "description": "d", "preview": "p"}\n```'

        planner = ActionPlanner.__new__(ActionPlanner)
        planner._registry = MagicMock()

        tools = [{"server": "srv", "tool": "t", "description": "d", "inputSchema": {}}]
        result = planner.plan("do it", tools)
        assert result["server"] == "srv"

    @patch("metatron.llm.chat_completion")
    def test_plan_llm_error_sanitized(self, mock_llm: MagicMock) -> None:
        from metatron.mcp.action_planner import ActionPlanner

        mock_llm.side_effect = RuntimeError("Connection to LLM timed out")

        planner = ActionPlanner.__new__(ActionPlanner)
        planner._registry = MagicMock()

        tools = [{"server": "srv", "tool": "t", "description": "d", "inputSchema": {}}]
        result = planner.plan("do something", tools)
        assert "error" in result
        assert "Action planning failed" in result["error"]
        assert "timed out" not in result["error"]

    def test_discover_write_tools_with_explicit(self, tmp_path: Path) -> None:
        from metatron.mcp.action_planner import ActionPlanner
        from metatron.mcp.config import MCPServerConfig
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        registry.add(MCPServerConfig(
            name="jira-mcp", command="echo",
            write_tools=["create_issue", "update_issue"],
        ))

        planner = ActionPlanner(registry)
        tools = planner.discover_write_tools()
        assert len(tools) == 2
        assert tools[0]["tool"] == "create_issue"
        assert tools[0]["server"] == "jira-mcp"


# ---------------------------------------------------------------------------
# ActionExecutor tests
# ---------------------------------------------------------------------------


class TestActionExecutor:
    """Tests for executing confirmed write actions."""

    def test_execute_calls_mcp_client(self, tmp_path: Path) -> None:
        from metatron.mcp.action_executor import ActionExecutor
        from metatron.mcp.config import MCPServerConfig
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        registry.add(MCPServerConfig(name="test-srv", command="echo"))

        action = PendingAction(
            user_id="u1", server_name="test-srv", tool_name="create_issue",
            arguments={"title": "Bug"}, description="Create bug", preview="",
        )

        mock_blocks = [{"type": "text", "text": "Issue PROJ-123 created"}]

        with patch("metatron.mcp.action_executor.MCPClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.call_tool = AsyncMock(return_value=mock_blocks)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock()
            MockClient.return_value = mock_instance

            executor = ActionExecutor(registry)
            result = executor.execute(action)

        assert result["success"] is True
        assert "PROJ-123" in result["result"]

    def test_execute_returns_error_on_failure(self, tmp_path: Path) -> None:
        from metatron.mcp.action_executor import ActionExecutor
        from metatron.mcp.config import MCPServerConfig
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        registry.add(MCPServerConfig(name="test-srv", command="echo"))

        action = PendingAction(
            user_id="u1", server_name="test-srv", tool_name="create_issue",
            arguments={}, description="Create bug", preview="",
        )

        with patch("metatron.mcp.action_executor.MCPClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(side_effect=RuntimeError("Connection refused"))
            MockClient.return_value = mock_instance

            executor = ActionExecutor(registry)
            result = executor.execute(action)

        assert result["success"] is False
        assert "Action execution failed" in result["error"]

    def test_execute_error_no_internal_details(self, tmp_path: Path) -> None:
        from metatron.mcp.action_executor import ActionExecutor
        from metatron.mcp.config import MCPServerConfig
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        registry.add(MCPServerConfig(name="test-srv", command="echo"))

        action = PendingAction(
            user_id="u1", server_name="test-srv", tool_name="create_issue",
            arguments={}, description="Create bug", preview="",
        )

        with patch("metatron.mcp.action_executor.MCPClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(
                side_effect=RuntimeError("SSL handshake failed: CERTIFICATE_VERIFY_FAILED"),
            )
            MockClient.return_value = mock_instance

            executor = ActionExecutor(registry)
            result = executor.execute(action)

        assert result["success"] is False
        assert "SSL" not in result["error"]
        assert "CERTIFICATE" not in result["error"]
        assert "Action execution failed" in result["error"]

    def test_execute_returns_error_for_unknown_server(self, tmp_path: Path) -> None:
        from metatron.mcp.action_executor import ActionExecutor
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        action = PendingAction(
            user_id="u1", server_name="nonexistent", tool_name="tool",
            arguments={}, description="test", preview="",
        )

        executor = ActionExecutor(registry)
        result = executor.execute(action)

        assert result["success"] is False
        assert "not found" in result["error"]


# ---------------------------------------------------------------------------
# ActionPolicy tests
# ---------------------------------------------------------------------------


class TestActionPolicy:
    """Tests for action policy (MVP: everything allowed, confirmation required)."""

    def test_is_allowed_returns_true(self) -> None:
        from metatron.mcp.action_planner import ActionPolicy

        assert ActionPolicy.is_allowed("any_user", "any_tool") is True

    def test_requires_confirmation_returns_true(self) -> None:
        from metatron.mcp.action_planner import ActionPolicy

        assert ActionPolicy.requires_confirmation("create_issue") is True
        assert ActionPolicy.requires_confirmation("delete_page") is True


# ---------------------------------------------------------------------------
# Router ACTION intent tests
# ---------------------------------------------------------------------------


class TestRouterActionIntent:
    """Tests for ACTION intent classification and handling in the router."""

    @pytest.fixture
    def settings(self) -> MagicMock:
        s = MagicMock()
        s.default_workspace_id = "TEST_WS"
        s.llm_provider = "deepseek"
        s.llm_fallback_provider = ""
        return s

    @pytest.fixture
    def router(self, settings: MagicMock) -> MagicMock:
        from metatron.agent.router import AgentRouter
        from metatron.agent.sessions import SessionManager
        SessionManager.reset_instance()
        return AgentRouter(settings=settings, sessions=SessionManager())

    def test_create_bug_classified_as_action(self, router: MagicMock) -> None:
        from metatron.agent.router import Intent
        assert router._classify("Создай баг в Jira про падение синка") == Intent.ACTION

    def test_create_page_classified_as_action(self, router: MagicMock) -> None:
        from metatron.agent.router import Intent
        assert router._classify("Create a wiki page about deployment") == Intent.ACTION

    def test_send_message_classified_as_action(self, router: MagicMock) -> None:
        from metatron.agent.router import Intent
        assert router._classify("Отправь сообщение в канал") == Intent.ACTION

    def test_write_report_classified_as_action(self, router: MagicMock) -> None:
        from metatron.agent.router import Intent
        assert router._classify("Write a sprint report") == Intent.ACTION

    def test_regular_query_not_action(self, router: MagicMock) -> None:
        from metatron.agent.router import Intent
        assert router._classify("what is MTRNIX-78 about?") == Intent.SEARCH

    @patch("metatron.mcp.action_planner.ActionPlanner.discover_write_tools")
    @patch("metatron.agent.router.hybrid_search_and_answer_sync")
    def test_action_no_tools_falls_back_to_search(
        self, mock_search: MagicMock, mock_discover: MagicMock, router: MagicMock,
    ) -> None:
        mock_discover.return_value = []
        mock_search.return_value = "Search result for creating"
        result = router.route("Create a bug report", user_id="u1")
        assert "Search result" in result
        mock_search.assert_called_once()

    @patch("metatron.mcp.action_planner.ActionPlanner.discover_write_tools")
    @patch("metatron.mcp.action_planner.ActionPlanner.plan")
    def test_action_stores_pending_and_returns_confirmation(
        self, mock_plan: MagicMock, mock_discover: MagicMock, router: MagicMock,
    ) -> None:
        mock_discover.return_value = [{"server": "jira", "tool": "create_issue", "description": "", "inputSchema": {}}]
        mock_plan.return_value = {
            "server": "jira",
            "tool": "create_issue",
            "arguments": {"title": "Bug: Sync failure"},
            "description": "Create Jira bug: Sync failure",
            "preview": "- Title: Bug: Sync failure\n- Type: Bug",
        }

        result = router.route("Создай баг про падение синка", user_id="u1")
        assert "Create Jira bug" in result
        assert "Confirm?" in result

        # Verify action is stored
        from metatron.mcp.action_store import get_action_store
        store = get_action_store()
        pending = store.get_for_user("u1")
        assert pending is not None
        assert pending.tool_name == "create_issue"

        # Cleanup
        store.remove(pending.action_id)

    @patch("metatron.mcp.action_executor.ActionExecutor.execute")
    def test_yes_confirmation_executes_action(
        self, mock_execute: MagicMock, router: MagicMock,
    ) -> None:
        from metatron.mcp.action_store import get_action_store

        store = get_action_store()
        action = PendingAction(
            user_id="u1", server_name="jira", tool_name="create_issue",
            arguments={"title": "Bug"}, description="Create bug", preview="",
        )
        store.add(action)

        mock_execute.return_value = {"success": True, "result": "Issue PROJ-123 created"}

        result = router.route("да", user_id="u1")
        assert "Done" in result
        assert "PROJ-123" in result
        assert store.get_for_user("u1") is None

    @patch("metatron.mcp.action_executor.ActionExecutor.execute")
    def test_no_confirmation_cancels_action(
        self, mock_execute: MagicMock, router: MagicMock,
    ) -> None:
        from metatron.mcp.action_store import get_action_store

        store = get_action_store()
        action = PendingAction(
            user_id="u1", server_name="jira", tool_name="create_issue",
            arguments={}, description="Create bug", preview="",
        )
        store.add(action)

        result = router.route("нет", user_id="u1")
        assert "cancelled" in result.lower()
        assert store.get_for_user("u1") is None
        mock_execute.assert_not_called()

    @patch("metatron.agent.router.hybrid_search_and_answer_sync")
    def test_non_confirmation_falls_through(
        self, mock_search: MagicMock, router: MagicMock,
    ) -> None:
        """If user sends non-yes/no text with pending action, treat as normal query."""
        from metatron.mcp.action_store import get_action_store

        store = get_action_store()
        action = PendingAction(
            user_id="u1", server_name="jira", tool_name="create_issue",
            arguments={}, description="Create bug", preview="",
        )
        store.add(action)

        mock_search.return_value = "Search result"
        result = router.route("what is MTRNIX-78?", user_id="u1")
        # Falls through to normal routing (search)
        assert "Search result" in result

        # Clean up pending action
        store.remove(action.action_id)


# ---------------------------------------------------------------------------
# Context-aware action tests
# ---------------------------------------------------------------------------


class TestContextAwareActions:
    """Tests for actions that pull context from the knowledge base."""

    @pytest.fixture
    def settings(self) -> MagicMock:
        s = MagicMock()
        s.default_workspace_id = "TEST_WS"
        s.llm_provider = "deepseek"
        s.llm_fallback_provider = ""
        return s

    @pytest.fixture
    def router(self, settings: MagicMock) -> MagicMock:
        from metatron.agent.router import AgentRouter
        from metatron.agent.sessions import SessionManager
        SessionManager.reset_instance()
        return AgentRouter(settings=settings, sessions=SessionManager())

    @patch("metatron.mcp.action_planner.ActionPlanner.discover_write_tools")
    @patch("metatron.mcp.action_planner.ActionPlanner.plan")
    @patch("metatron.agent.router.hybrid_search_and_answer_sync")
    def test_summary_triggers_search_context(
        self, mock_search: MagicMock, mock_plan: MagicMock,
        mock_discover: MagicMock, router: MagicMock,
    ) -> None:
        mock_discover.return_value = [{"server": "wiki", "tool": "create_page", "description": "", "inputSchema": {}}]
        mock_search.return_value = "Sprint 12: completed 5 stories, 2 bugs fixed"
        mock_plan.return_value = {
            "server": "wiki", "tool": "create_page",
            "arguments": {"title": "Sprint Summary"},
            "description": "Create sprint summary page",
            "preview": "Title: Sprint Summary",
        }

        result = router.route("Create sprint summary page", user_id="u1")

        # Verify search was called for context
        mock_search.assert_called_once()
        # Verify context was passed to planner
        mock_plan.assert_called_once()
        call_kwargs = mock_plan.call_args
        assert "Sprint 12" in call_kwargs.kwargs.get("context", "") or \
               "Sprint 12" in (call_kwargs.args[2] if len(call_kwargs.args) > 2 else "")

        # Cleanup
        from metatron.mcp.action_store import get_action_store
        store = get_action_store()
        pending = store.get_for_user("u1")
        if pending:
            store.remove(pending.action_id)

    @patch("metatron.mcp.action_planner.ActionPlanner.discover_write_tools")
    @patch("metatron.mcp.action_planner.ActionPlanner.plan")
    def test_non_summary_action_no_context(
        self, mock_plan: MagicMock, mock_discover: MagicMock, router: MagicMock,
    ) -> None:
        mock_discover.return_value = [{"server": "jira", "tool": "create_issue", "description": "", "inputSchema": {}}]
        mock_plan.return_value = {
            "server": "jira", "tool": "create_issue",
            "arguments": {"title": "Bug"},
            "description": "Create bug", "preview": "Title: Bug",
        }

        with patch("metatron.agent.router.hybrid_search_and_answer_sync") as mock_search:
            router.route("Создай баг про ошибку", user_id="u1")
            # No context keywords → search NOT called
            mock_search.assert_not_called()

        # Cleanup
        from metatron.mcp.action_store import get_action_store
        store = get_action_store()
        pending = store.get_for_user("u1")
        if pending:
            store.remove(pending.action_id)
