"""Unit tests for metronix_memory_get_context MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from metronix.core.models import AssembledContext
from metronix.mcp.principal import MCPPrincipal, bind_principal, reset_principal
from metronix.mcp.tools.memory_context import metronix_memory_get_context


class TestMemoryGetContextFlagOff:
    """When memory_injection_enabled=False, returns empty response."""

    async def test_returns_empty_when_flag_off(self) -> None:
        with patch("metronix.core.config.get_settings") as mock_get:
            mock_get.return_value = MagicMock(memory_injection_enabled=False)
            result = await metronix_memory_get_context(
                agent_id="agent-1",
                workspace_id="WS1",
                query="test",
            )

        assert result["system_prompt"] == ""
        assert result["preferences_count"] == 0
        assert result["memories_count"] == 0


class TestMemoryGetContextValidation:
    """Parameter validation."""

    async def test_missing_agent_id(self) -> None:
        result = await metronix_memory_get_context(
            agent_id="",
            workspace_id="WS1",
            query="test",
        )
        assert "error" in result

    async def test_missing_workspace_id(self) -> None:
        result = await metronix_memory_get_context(
            agent_id="agent-1",
            workspace_id="",
            query="test",
        )
        assert "error" in result

    async def test_missing_query(self) -> None:
        result = await metronix_memory_get_context(
            agent_id="agent-1",
            workspace_id="WS1",
            query="",
        )
        assert "error" in result

    async def test_whitespace_query(self) -> None:
        result = await metronix_memory_get_context(
            agent_id="agent-1",
            workspace_id="WS1",
            query="   ",
        )
        assert "error" in result

    async def test_ungranted_workspace_does_not_build_memory_service(self) -> None:
        token = bind_principal(MCPPrincipal("u1", "viewer", ("ws-a",)))
        try:
            with patch(
                "metronix.mcp.tools.memory_context._memory_deps.build_memory_service_for_workspace",
                new=AsyncMock(),
            ) as build_service:
                result = await metronix_memory_get_context(
                    agent_id="agent-1",
                    workspace_id="ws-b",
                    query="test",
                )
        finally:
            reset_principal(token)

        assert "No access to workspace 'ws-b'" in result["error"]["message"]
        build_service.assert_not_awaited()


class TestMemoryGetContextWithAssembler:
    """When flag is on, delegates to AgentContextAssembler."""

    async def test_returns_assembled_context(self) -> None:
        mock_settings = MagicMock(
            memory_injection_enabled=True,
            memory_injection_facts_top_k=10,
        )

        mock_ctx = AssembledContext(
            system_prompt="<preferences>\npref\n</preferences>",
            preferences_count=1,
            memories_count=3,
            tokens_budget={"preferences": 10, "memories": 50},
        )

        mock_assembler = AsyncMock()
        mock_assembler.assemble.return_value = mock_ctx

        mock_service = AsyncMock()
        mock_service._search = AsyncMock()

        # Patch at the source modules — the MCP tool imports locally.
        with (
            patch(
                "metronix.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch("metronix.mcp.tools.memory_context._memory_deps") as mock_deps,
            patch(
                "metronix.memory.assembler.AgentContextAssembler",
                return_value=mock_assembler,
            ),
        ):
            mock_deps.build_memory_service_for_workspace = AsyncMock(
                return_value=mock_service,
            )

            result = await metronix_memory_get_context(
                agent_id="agent-1",
                workspace_id="WS1",
                query="What is the status?",
                memory_top_k=5,
            )

        assert result["system_prompt"] == "<preferences>\npref\n</preferences>"
        assert result["preferences_count"] == 1
        assert result["memories_count"] == 3


class TestMemoryGetContextDefaultTopK:
    """When memory_top_k is 0 or not provided, uses settings default."""

    async def test_default_top_k_from_settings(self) -> None:
        mock_settings = MagicMock(
            memory_injection_enabled=True,
            memory_injection_facts_top_k=15,
        )

        mock_ctx = AssembledContext(
            system_prompt="",
            preferences_count=0,
            memories_count=0,
        )
        mock_assembler = AsyncMock()
        mock_assembler.assemble.return_value = mock_ctx

        mock_service = AsyncMock()
        mock_service._search = AsyncMock()

        with (
            patch(
                "metronix.core.config.get_settings",
                return_value=mock_settings,
            ),
            patch("metronix.mcp.tools.memory_context._memory_deps") as mock_deps,
            patch(
                "metronix.memory.assembler.AgentContextAssembler",
                return_value=mock_assembler,
            ),
        ):
            mock_deps.build_memory_service_for_workspace = AsyncMock(
                return_value=mock_service,
            )

            await metronix_memory_get_context(
                agent_id="agent-1",
                workspace_id="WS1",
                query="test",
                memory_top_k=0,  # Should fall back to settings default (15)
            )

        mock_assembler.assemble.assert_called_once_with(
            agent_id="agent-1",
            workspace_id="WS1",
            user_message="test",
            memory_top_k=15,
        )
