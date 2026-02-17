"""Tests for MCP client modules: config, client, registry, adapter, sync."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.mcp.config import MCPServerConfig


# ---------------------------------------------------------------------------
# MCPServerConfig tests
# ---------------------------------------------------------------------------


class TestMCPServerConfig:
    """Tests for MCPServerConfig Pydantic model."""

    def test_minimal_config(self) -> None:
        cfg = MCPServerConfig(name="test", command="echo")
        assert cfg.name == "test"
        assert cfg.command == "echo"
        assert cfg.args == []
        assert cfg.env == {}
        assert cfg.enabled is True

    def test_full_config(self) -> None:
        cfg = MCPServerConfig(
            name="github-mcp",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_TOKEN": "xxx"},
            workspace_id="WS1",
            enabled=False,
            read_tools=["list_repos"],
            description="GitHub via MCP",
        )
        assert cfg.name == "github-mcp"
        assert cfg.args == ["-y", "@modelcontextprotocol/server-github"]
        assert cfg.env == {"GITHUB_TOKEN": "xxx"}
        assert cfg.workspace_id == "WS1"
        assert cfg.enabled is False
        assert cfg.read_tools == ["list_repos"]

    def test_serialization_roundtrip(self) -> None:
        cfg = MCPServerConfig(
            name="test-srv",
            command="python",
            args=["-m", "my_server"],
            env={"KEY": "val"},
        )
        data = cfg.model_dump()
        restored = MCPServerConfig(**data)
        assert restored.name == cfg.name
        assert restored.command == cfg.command
        assert restored.args == cfg.args
        assert restored.env == cfg.env


# ---------------------------------------------------------------------------
# MCPServerRegistry tests
# ---------------------------------------------------------------------------


class TestMCPServerRegistry:
    """Tests for file-based MCP server registry."""

    def test_add_and_list(self, tmp_path: Path) -> None:
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        cfg = MCPServerConfig(name="srv1", command="echo", workspace_id="WS")
        registry.add(cfg)

        servers = registry.list_servers()
        assert len(servers) == 1
        assert servers[0].name == "srv1"

    def test_remove(self, tmp_path: Path) -> None:
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        registry.add(MCPServerConfig(name="srv1", command="echo"))
        assert registry.remove("srv1") is True
        assert registry.remove("srv1") is False
        assert registry.list_servers() == []

    def test_get(self, tmp_path: Path) -> None:
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        registry.add(MCPServerConfig(name="srv1", command="echo"))
        assert registry.get("srv1") is not None
        assert registry.get("missing") is None

    def test_persistence(self, tmp_path: Path) -> None:
        from metatron.mcp.registry import MCPServerRegistry

        r1 = MCPServerRegistry(str(tmp_path))
        r1.add(MCPServerConfig(name="srv1", command="echo", args=["hello"]))

        # Load from same file
        r2 = MCPServerRegistry(str(tmp_path))
        servers = r2.list_servers()
        assert len(servers) == 1
        assert servers[0].name == "srv1"
        assert servers[0].args == ["hello"]

    def test_workspace_filter(self, tmp_path: Path) -> None:
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        registry.add(MCPServerConfig(name="s1", command="a", workspace_id="WS1"))
        registry.add(MCPServerConfig(name="s2", command="b", workspace_id="WS2"))
        registry.add(MCPServerConfig(name="s3", command="c", workspace_id=""))

        ws1 = registry.list_servers("WS1")
        # s1 (WS1) + s3 (no workspace = global)
        assert len(ws1) == 2
        names = {s.name for s in ws1}
        assert "s1" in names
        assert "s3" in names

    def test_list_enabled(self, tmp_path: Path) -> None:
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        registry.add(MCPServerConfig(name="s1", command="a", enabled=True))
        registry.add(MCPServerConfig(name="s2", command="b", enabled=False))

        enabled = registry.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].name == "s1"

    def test_corrupted_file(self, tmp_path: Path) -> None:
        from metatron.mcp.registry import MCPServerRegistry

        state_file = tmp_path / "mcp_servers.json"
        state_file.write_text("not valid json{{{")

        registry = MCPServerRegistry(str(tmp_path))
        assert registry.list_servers() == []

    def test_update_existing(self, tmp_path: Path) -> None:
        from metatron.mcp.registry import MCPServerRegistry

        registry = MCPServerRegistry(str(tmp_path))
        registry.add(MCPServerConfig(name="srv1", command="old"))
        registry.add(MCPServerConfig(name="srv1", command="new"))

        servers = registry.list_servers()
        assert len(servers) == 1
        assert servers[0].command == "new"


# ---------------------------------------------------------------------------
# Adapter: tool classification tests
# ---------------------------------------------------------------------------


class TestToolClassification:
    """Tests for classify_tool and select_read_tools."""

    def test_classify_read_tool(self) -> None:
        from metatron.mcp.adapter import classify_tool

        assert classify_tool("list_repos", "List all repositories") == "read"
        assert classify_tool("search_code", "Search for code") == "read"
        assert classify_tool("get_file", "Get file contents") == "read"

    def test_classify_write_tool(self) -> None:
        from metatron.mcp.adapter import classify_tool

        assert classify_tool("create_issue", "Create a new issue") == "write"
        assert classify_tool("delete_branch", "Delete a branch") == "write"
        assert classify_tool("update_file", "Update file contents") == "write"

    def test_classify_ambiguous_defaults_read(self) -> None:
        from metatron.mcp.adapter import classify_tool

        assert classify_tool("do_something", "Does stuff") == "read"

    def test_select_read_tools(self) -> None:
        from metatron.mcp.adapter import select_read_tools

        tools = [
            {"name": "list_repos", "description": "List repos"},
            {"name": "create_issue", "description": "Create an issue"},
            {"name": "search_code", "description": "Search code"},
        ]
        read = select_read_tools(tools)
        names = [t["name"] for t in read]
        assert "list_repos" in names
        assert "search_code" in names
        assert "create_issue" not in names

    def test_select_explicit_tools(self) -> None:
        from metatron.mcp.adapter import select_read_tools

        tools = [
            {"name": "list_repos", "description": "List repos"},
            {"name": "create_issue", "description": "Create an issue"},
        ]
        selected = select_read_tools(tools, explicit_tools=["create_issue"])
        assert len(selected) == 1
        assert selected[0]["name"] == "create_issue"


# ---------------------------------------------------------------------------
# Adapter: get_adapter + register_adapter tests
# ---------------------------------------------------------------------------


class TestAdapterRegistry:
    """Tests for adapter registry and selection."""

    def test_default_generic_adapter(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter, get_adapter

        cfg = MCPServerConfig(name="unknown-srv", command="echo")
        adapter = get_adapter(cfg)
        assert isinstance(adapter, GenericMCPAdapter)

    def test_registered_adapter(self) -> None:
        from metatron.mcp.adapter import (
            GenericMCPAdapter,
            _ADAPTER_REGISTRY,
            get_adapter,
            register_adapter,
        )

        class CustomAdapter(GenericMCPAdapter):
            pass

        register_adapter("custom", CustomAdapter)
        try:
            cfg = MCPServerConfig(name="custom-server", command="echo")
            adapter = get_adapter(cfg)
            assert isinstance(adapter, CustomAdapter)
        finally:
            _ADAPTER_REGISTRY.pop("custom", None)


# ---------------------------------------------------------------------------
# Adapter: GenericMCPAdapter._results_to_documents tests
# ---------------------------------------------------------------------------


class TestGenericMCPAdapter:
    """Tests for document conversion from MCP results."""

    def test_results_to_documents(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(name="test-srv", command="echo")
        adapter = GenericMCPAdapter(cfg)

        blocks = [
            {"type": "text", "text": "Hello world"},
            {"type": "text", "text": "Another doc"},
        ]
        docs = adapter._results_to_documents(blocks, "read_data", "WS1")
        assert len(docs) == 2
        assert docs[0].source_type == "mcp"
        assert docs[0].workspace_id == "WS1"
        assert "test-srv" in docs[0].source_id
        assert docs[0].content == "Hello world"
        assert docs[0].metadata["mcp_server"] == "test-srv"
        assert docs[0].metadata["mcp_tool"] == "read_data"

    def test_empty_blocks_skipped(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(name="test-srv", command="echo")
        adapter = GenericMCPAdapter(cfg)

        blocks = [
            {"type": "text", "text": ""},
            {"type": "text", "text": "   "},
            {"type": "text", "text": "valid"},
        ]
        docs = adapter._results_to_documents(blocks, "tool", "WS1")
        assert len(docs) == 1
        assert docs[0].content == "valid"

    def test_unique_source_ids(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(name="test-srv", command="echo")
        adapter = GenericMCPAdapter(cfg)

        blocks = [
            {"type": "text", "text": "doc A"},
            {"type": "text", "text": "doc B"},
        ]
        docs = adapter._results_to_documents(blocks, "tool", "WS1")
        assert docs[0].source_id != docs[1].source_id


# ---------------------------------------------------------------------------
# MCPSyncManager tests
# ---------------------------------------------------------------------------


class TestMCPSyncManager:
    """Tests for sync manager with hash-based incremental."""

    def test_content_hash(self) -> None:
        from metatron.mcp.sync import MCPSyncManager

        mgr = MCPSyncManager.__new__(MCPSyncManager)
        h1 = mgr._content_hash("hello")
        h2 = mgr._content_hash("hello")
        h3 = mgr._content_hash("world")
        assert h1 == h2
        assert h1 != h3

    def test_filter_changed_new_docs(self, tmp_path: Path) -> None:
        from metatron.core.models import Document
        from metatron.mcp.sync import MCPSyncManager

        mgr = MCPSyncManager(state_dir=str(tmp_path))
        docs = [
            Document(source_id="d1", content="text one"),
            Document(source_id="d2", content="text two"),
        ]
        changed = mgr._filter_changed(docs)
        assert len(changed) == 2

    def test_filter_changed_skips_unchanged(self, tmp_path: Path) -> None:
        from metatron.core.models import Document
        from metatron.mcp.sync import MCPSyncManager

        mgr = MCPSyncManager(state_dir=str(tmp_path))
        docs = [Document(source_id="d1", content="same text")]

        # First call: all new
        changed1 = mgr._filter_changed(docs)
        assert len(changed1) == 1

        # Second call: unchanged
        changed2 = mgr._filter_changed(docs)
        assert len(changed2) == 0

    def test_filter_changed_detects_update(self, tmp_path: Path) -> None:
        from metatron.core.models import Document
        from metatron.mcp.sync import MCPSyncManager

        mgr = MCPSyncManager(state_dir=str(tmp_path))

        docs1 = [Document(source_id="d1", content="version 1")]
        mgr._filter_changed(docs1)

        docs2 = [Document(source_id="d1", content="version 2")]
        changed = mgr._filter_changed(docs2)
        assert len(changed) == 1

    def test_hash_persistence(self, tmp_path: Path) -> None:
        from metatron.core.models import Document
        from metatron.mcp.sync import MCPSyncManager

        m1 = MCPSyncManager(state_dir=str(tmp_path))
        m1._filter_changed([Document(source_id="d1", content="text")])
        m1._save_hashes()

        # New manager loads hashes from disk
        m2 = MCPSyncManager(state_dir=str(tmp_path))
        changed = m2._filter_changed([Document(source_id="d1", content="text")])
        assert len(changed) == 0  # unchanged

    @pytest.mark.asyncio
    async def test_sync_server_no_docs(self, tmp_path: Path) -> None:
        from metatron.mcp.sync import MCPSyncManager

        cfg = MCPServerConfig(name="empty-srv", command="echo")
        mgr = MCPSyncManager(state_dir=str(tmp_path))

        with patch("metatron.mcp.sync.get_adapter") as mock_adapter:
            adapter = AsyncMock()
            adapter.fetch_documents = AsyncMock(return_value=[])
            mock_adapter.return_value = adapter

            result = await mgr.sync_server(cfg, "WS1")

        assert result.documents_fetched == 0

    @pytest.mark.asyncio
    async def test_sync_server_with_docs(self, tmp_path: Path) -> None:
        from metatron.core.models import Document
        from metatron.mcp.sync import MCPSyncManager

        cfg = MCPServerConfig(name="test-srv", command="echo")
        mgr = MCPSyncManager(state_dir=str(tmp_path))

        docs = [Document(source_id="d1", content="hello world", source_type="mcp")]

        with patch("metatron.mcp.sync.get_adapter") as mock_adapter, \
             patch("metatron.ingestion.pipeline.ingest_documents") as mock_ingest:
            adapter = AsyncMock()
            adapter.fetch_documents = AsyncMock(return_value=docs)
            mock_adapter.return_value = adapter

            from metatron.core.models import SyncResult
            mock_ingest.return_value = SyncResult(
                connector_type="mcp:test-srv",
                workspace_id="WS1",
                documents_new=1,
            )

            result = await mgr.sync_server(cfg, "WS1")

        assert result.documents_new == 1
        mock_ingest.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_server_force_full(self, tmp_path: Path) -> None:
        from metatron.core.models import Document, SyncResult
        from metatron.mcp.sync import MCPSyncManager

        cfg = MCPServerConfig(name="test-srv", command="echo")
        mgr = MCPSyncManager(state_dir=str(tmp_path))

        docs = [Document(source_id="d1", content="hello")]

        # Pre-seed same hash
        mgr._hashes["d1"] = mgr._content_hash("hello")

        with patch("metatron.mcp.sync.get_adapter") as mock_adapter, \
             patch("metatron.ingestion.pipeline.ingest_documents") as mock_ingest:
            adapter = AsyncMock()
            adapter.fetch_documents = AsyncMock(return_value=docs)
            mock_adapter.return_value = adapter
            mock_ingest.return_value = SyncResult(documents_new=1)

            result = await mgr.sync_server(cfg, "WS1", force_full=True)

        # force_full bypasses hash check
        mock_ingest.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_all_empty(self, tmp_path: Path) -> None:
        from metatron.mcp.registry import MCPServerRegistry
        from metatron.mcp.sync import MCPSyncManager

        registry = MCPServerRegistry(str(tmp_path))
        mgr = MCPSyncManager(registry, str(tmp_path))

        results = await mgr.sync_all("WS1")
        assert results == []

    @pytest.mark.asyncio
    async def test_sync_all_handles_error(self, tmp_path: Path) -> None:
        from metatron.mcp.registry import MCPServerRegistry
        from metatron.mcp.sync import MCPSyncManager

        registry = MCPServerRegistry(str(tmp_path))
        registry.add(MCPServerConfig(name="broken", command="nope"))

        mgr = MCPSyncManager(registry, str(tmp_path))

        with patch("metatron.mcp.sync.get_adapter") as mock_adapter:
            adapter = AsyncMock()
            adapter.fetch_documents = AsyncMock(side_effect=RuntimeError("fail"))
            mock_adapter.return_value = adapter

            results = await mgr.sync_all("WS1")

        assert len(results) == 1
        name, result = results[0]
        assert name == "broken"
        assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# MCPClient tests (mocked SDK)
# ---------------------------------------------------------------------------


class TestMCPClient:
    """Tests for MCPClient with mocked MCP SDK."""

    def _mock_mcp_sdk(self) -> dict:
        """Create mock MCP SDK objects."""
        mock_tool = MagicMock()
        mock_tool.name = "read_file"
        mock_tool.description = "Read a file"
        mock_tool.inputSchema = {"type": "object"}

        mock_list_result = MagicMock()
        mock_list_result.tools = [mock_tool]

        mock_content_block = MagicMock()
        mock_content_block.type = "text"
        mock_content_block.text = "file contents here"

        mock_call_result = MagicMock()
        mock_call_result.content = [mock_content_block]

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_list_result)
        mock_session.call_tool = AsyncMock(return_value=mock_call_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        mock_stdio_ctx = AsyncMock()
        mock_read = MagicMock()
        mock_write = MagicMock()
        mock_stdio_ctx.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
        mock_stdio_ctx.__aexit__ = AsyncMock()

        return {
            "session": mock_session,
            "stdio_ctx": mock_stdio_ctx,
            "list_result": mock_list_result,
            "call_result": mock_call_result,
        }

    @pytest.mark.asyncio
    async def test_list_tools(self) -> None:
        import metatron.mcp.client as client_mod

        mocks = self._mock_mcp_sdk()
        cfg = MCPServerConfig(name="test", command="echo")

        with patch.object(client_mod, "_ClientSession", return_value=mocks["session"]), \
             patch.object(client_mod, "_StdioServerParameters", return_value=MagicMock()), \
             patch.object(client_mod, "_stdio_client", return_value=mocks["stdio_ctx"]):
            # Mark as already imported
            client_mod._ClientSession = MagicMock(return_value=mocks["session"])
            client_mod._StdioServerParameters = MagicMock()
            client_mod._stdio_client = MagicMock(return_value=mocks["stdio_ctx"])

            from metatron.mcp.client import MCPClient
            client = MCPClient(cfg)
            await client.connect()
            tools = await client.list_tools()
            await client.disconnect()

        assert len(tools) == 1
        assert tools[0]["name"] == "read_file"
        assert tools[0]["description"] == "Read a file"

    @pytest.mark.asyncio
    async def test_call_tool(self) -> None:
        import metatron.mcp.client as client_mod

        mocks = self._mock_mcp_sdk()
        cfg = MCPServerConfig(name="test", command="echo")

        client_mod._ClientSession = MagicMock(return_value=mocks["session"])
        client_mod._StdioServerParameters = MagicMock()
        client_mod._stdio_client = MagicMock(return_value=mocks["stdio_ctx"])

        from metatron.mcp.client import MCPClient
        client = MCPClient(cfg)
        await client.connect()
        result = await client.call_tool("read_file", {"path": "/test"})
        await client.disconnect()

        assert len(result) == 1
        assert result[0]["text"] == "file contents here"

    @pytest.mark.asyncio
    async def test_not_connected_raises(self) -> None:
        from metatron.mcp.client import MCPClient

        cfg = MCPServerConfig(name="test", command="echo")
        client = MCPClient(cfg)

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.list_tools()

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.call_tool("anything")

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        import metatron.mcp.client as client_mod

        mocks = self._mock_mcp_sdk()
        cfg = MCPServerConfig(name="test", command="echo")

        client_mod._ClientSession = MagicMock(return_value=mocks["session"])
        client_mod._StdioServerParameters = MagicMock()
        client_mod._stdio_client = MagicMock(return_value=mocks["stdio_ctx"])

        from metatron.mcp.client import MCPClient

        async with MCPClient(cfg) as client:
            assert client.connected is True

        assert client.connected is False

    @pytest.mark.asyncio
    async def test_disconnect_suppresses_cleanup_error(self) -> None:
        """Bug fix: disconnect cleanup errors don't propagate."""
        import metatron.mcp.client as client_mod

        mocks = self._mock_mcp_sdk()
        cfg = MCPServerConfig(name="test", command="echo")

        # Make session __aexit__ raise (simulates cancel scope error)
        mocks["session"].__aexit__ = AsyncMock(
            side_effect=RuntimeError("cancel scope in different task"),
        )

        client_mod._ClientSession = MagicMock(return_value=mocks["session"])
        client_mod._StdioServerParameters = MagicMock()
        client_mod._stdio_client = MagicMock(return_value=mocks["stdio_ctx"])

        from metatron.mcp.client import MCPClient

        client = MCPClient(cfg)
        await client.connect()
        # Should not raise
        await client.disconnect()
        assert client.connected is False


# ---------------------------------------------------------------------------
# Adapter: two-phase fetch tests
# ---------------------------------------------------------------------------


class TestAdapterTwoPhase:
    """Tests for the two-phase GenericMCPAdapter (discover + read)."""

    def test_parse_directories_json(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        text = '["/home/user/docs", "/home/user/code"]'
        dirs = GenericMCPAdapter._parse_directories(text)
        assert dirs == ["/home/user/docs", "/home/user/code"]

    def test_parse_directories_lines(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        text = "[DIR] /home/user/docs\n[DIR] /home/user/code\n"
        dirs = GenericMCPAdapter._parse_directories(text)
        assert dirs == ["/home/user/docs", "/home/user/code"]

    def test_parse_directories_empty(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        assert GenericMCPAdapter._parse_directories("") == []
        assert GenericMCPAdapter._parse_directories("  \n  ") == []

    def test_parse_directories_allowed_prefix(self) -> None:
        """Bug fix: 'Allowed directories:' prefix should be skipped."""
        from metatron.mcp.adapter import GenericMCPAdapter

        text = "Allowed directories:\n/private/tmp/test-docs"
        dirs = GenericMCPAdapter._parse_directories(text)
        assert dirs == ["/private/tmp/test-docs"]

    def test_parse_directories_private_tmp(self) -> None:
        """Bug fix: macOS /private/tmp paths should be preserved."""
        from metatron.mcp.adapter import GenericMCPAdapter

        text = (
            "Allowed directories:\n"
            "/private/tmp/project-a\n"
            "/private/tmp/project-b\n"
        )
        dirs = GenericMCPAdapter._parse_directories(text)
        assert dirs == ["/private/tmp/project-a", "/private/tmp/project-b"]

    def test_parse_directories_skips_non_path_lines(self) -> None:
        """Non-path lines like labels and descriptions should be ignored."""
        from metatron.mcp.adapter import GenericMCPAdapter

        text = (
            "Allowed directories:\n"
            "These are the accessible paths:\n"
            "/home/user/docs\n"
            "Note: read-only\n"
        )
        dirs = GenericMCPAdapter._parse_directories(text)
        assert dirs == ["/home/user/docs"]

    def test_parse_directory_listing_file_tags(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        text = (
            "[FILE] readme.md\n"
            "[DIR] subdir/\n"
            "[FILE] main.py\n"
            "[FILE] image.png\n"  # not a text extension
        )
        files = GenericMCPAdapter._parse_directory_listing(text)
        assert "readme.md" in files
        assert "main.py" in files
        assert "image.png" not in files
        # dirs are skipped
        assert not any("subdir" in f for f in files)

    def test_parse_directory_listing_json(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        text = '["src/main.py", "docs/readme.md", "logo.png"]'
        files = GenericMCPAdapter._parse_directory_listing(text)
        assert "src/main.py" in files
        assert "docs/readme.md" in files
        assert "logo.png" not in files  # not text

    def test_parse_directory_listing_empty(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        assert GenericMCPAdapter._parse_directory_listing("") == []

    def test_find_get_tool_prefers_config(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(
            name="test", command="echo", get_tool="custom_read",
        )
        adapter = GenericMCPAdapter(cfg)
        tools = [
            {"name": "read_file", "description": "Read file"},
            {"name": "custom_read", "description": "Custom reader"},
        ]
        found = adapter._find_get_tool(tools)
        assert found is not None
        assert found["name"] == "custom_read"

    def test_find_get_tool_auto_detect(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(name="test", command="echo")
        adapter = GenericMCPAdapter(cfg)
        tools = [
            {"name": "list_directory", "description": "List dir"},
            {"name": "read_text_file", "description": "Read text file"},
            {"name": "read_file", "description": "Read file"},
        ]
        found = adapter._find_get_tool(tools)
        assert found is not None
        assert found["name"] == "read_text_file"  # higher priority

    def test_find_get_tool_none(self) -> None:
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(name="test", command="echo")
        adapter = GenericMCPAdapter(cfg)
        tools = [
            {"name": "create_file", "description": "Create file"},
        ]
        assert adapter._find_get_tool(tools) is None

    @pytest.mark.asyncio
    async def test_fetch_discovers_and_reads(self) -> None:
        """Full two-phase: list_directory → read_text_file for each file."""
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(name="fs-srv", command="echo")
        adapter = GenericMCPAdapter(cfg)

        # Mock MCPClient
        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[
            {"name": "list_directory", "description": "List directory"},
            {"name": "read_text_file", "description": "Read text file"},
        ])

        # list_directory returns file listing
        listing_blocks = [{"type": "text", "text": (
            "[FILE] src/main.py\n"
            "[FILE] docs/readme.md\n"
            "[DIR] build/\n"
            "[FILE] logo.png\n"
        )}]
        # read_text_file returns file content
        file1_blocks = [{"type": "text", "text": "print('hello')"}]
        file2_blocks = [{"type": "text", "text": "# README"}]

        def call_tool_side_effect(name: str, args: dict | None = None) -> list:
            if name == "list_directory":
                return listing_blocks
            if name == "read_text_file":
                path = (args or {}).get("path", "")
                if "main.py" in path:
                    return file1_blocks
                if "readme.md" in path:
                    return file2_blocks
            return []

        mock_client.call_tool = AsyncMock(side_effect=call_tool_side_effect)

        with patch("metatron.mcp.adapter.MCPClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock()

            docs = await adapter.fetch_documents("WS1")

        assert len(docs) == 2
        contents = {d.content for d in docs}
        assert "print('hello')" in contents
        assert "# README" in contents
        # Verify path metadata
        for doc in docs:
            assert "path" in doc.metadata

    @pytest.mark.asyncio
    async def test_fetch_no_get_tool_returns_empty(self) -> None:
        """If no read tool found, return empty."""
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(name="no-read-srv", command="echo")
        adapter = GenericMCPAdapter(cfg)

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[
            {"name": "create_issue", "description": "Create issue"},
        ])

        with patch("metatron.mcp.adapter.MCPClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock()

            docs = await adapter.fetch_documents("WS1")

        assert docs == []

    @pytest.mark.asyncio
    async def test_fetch_via_roots(self) -> None:
        """Two-phase via list_allowed_directories + list_directory."""
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(name="fs-srv", command="echo")
        adapter = GenericMCPAdapter(cfg)

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[
            {"name": "list_allowed_directories", "description": "Allowed dirs"},
            {"name": "list_directory", "description": "List directory"},
            {"name": "read_text_file", "description": "Read text file"},
        ])

        def call_tool_side_effect(name: str, args: dict | None = None) -> list:
            if name == "list_allowed_directories":
                return [{"type": "text", "text": "/home/user/docs"}]
            if name == "list_directory":
                return [{"type": "text", "text": "[FILE] notes.md\n[FILE] pic.jpg"}]
            if name == "read_text_file":
                return [{"type": "text", "text": "Some notes content"}]
            return []

        mock_client.call_tool = AsyncMock(side_effect=call_tool_side_effect)

        with patch("metatron.mcp.adapter.MCPClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock()

            docs = await adapter.fetch_documents("WS1")

        assert len(docs) == 1
        assert docs[0].content == "Some notes content"

    @pytest.mark.asyncio
    async def test_fetch_read_error_skips_file(self) -> None:
        """If reading a file fails, skip it gracefully."""
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(name="fs-srv", command="echo")
        adapter = GenericMCPAdapter(cfg)

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[
            {"name": "list_directory", "description": "List directory"},
            {"name": "read_text_file", "description": "Read text file"},
        ])

        call_count = 0

        def call_tool_side_effect(name: str, args: dict | None = None) -> list:
            nonlocal call_count
            if name == "list_directory":
                return [{"type": "text", "text": "[FILE] a.py\n[FILE] b.py"}]
            if name == "read_text_file":
                call_count += 1
                if call_count == 1:
                    raise RuntimeError("Permission denied")
                return [{"type": "text", "text": "good content"}]
            return []

        mock_client.call_tool = AsyncMock(side_effect=call_tool_side_effect)

        with patch("metatron.mcp.adapter.MCPClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock()

            docs = await adapter.fetch_documents("WS1")

        assert len(docs) == 1
        assert docs[0].content == "good content"

    @pytest.mark.asyncio
    async def test_fetch_via_search_fallback(self) -> None:
        """Fallback to search_files when no list tool exists."""
        from metatron.mcp.adapter import GenericMCPAdapter

        cfg = MCPServerConfig(name="srv", command="echo")
        adapter = GenericMCPAdapter(cfg)

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[
            {"name": "search_files", "description": "Search files"},
            {"name": "read_text_file", "description": "Read text file"},
        ])

        def call_tool_side_effect(name: str, args: dict | None = None) -> list:
            if name == "search_files":
                return [{"type": "text", "text": "found.py\ndata.csv\nimage.bmp"}]
            if name == "read_text_file":
                path = (args or {}).get("path", "")
                if "found.py" in path:
                    return [{"type": "text", "text": "# python code"}]
                if "data.csv" in path:
                    return [{"type": "text", "text": "a,b,c"}]
            return []

        mock_client.call_tool = AsyncMock(side_effect=call_tool_side_effect)

        with patch("metatron.mcp.adapter.MCPClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock()

            docs = await adapter.fetch_documents("WS1")

        assert len(docs) == 2
        contents = {d.content for d in docs}
        assert "# python code" in contents
        assert "a,b,c" in contents

    def test_is_text_file(self) -> None:
        from metatron.mcp.adapter import _is_text_file

        assert _is_text_file("readme.md") is True
        assert _is_text_file("src/main.py") is True
        assert _is_text_file("config.yaml") is True
        assert _is_text_file("data.json") is True
        assert _is_text_file("image.png") is False
        assert _is_text_file("archive.zip") is False
        assert _is_text_file("video.mp4") is False

    def test_extract_text_list_dict(self) -> None:
        """Bug fix: _extract_text handles list[dict] from call_tool."""
        from metatron.mcp.adapter import _extract_text

        blocks = [
            {"type": "text", "text": "line 1"},
            {"type": "text", "text": ""},
            {"type": "text", "text": "line 2"},
        ]
        assert _extract_text(blocks) == "line 1\nline 2"
        assert _extract_text([]) == ""

    def test_extract_text_sdk_objects(self) -> None:
        """Bug fix: _extract_text handles SDK objects with .content attr."""
        from metatron.mcp.adapter import _extract_text

        block1 = MagicMock()
        block1.text = "hello"
        block2 = MagicMock()
        block2.text = "world"

        # SDK result object with .content list
        sdk_result = MagicMock()
        sdk_result.content = [block1, block2]

        assert _extract_text(sdk_result) == "hello\nworld"

    def test_extract_text_empty_sdk(self) -> None:
        """_extract_text returns empty for SDK object with no content."""
        from metatron.mcp.adapter import _extract_text

        sdk_result = MagicMock()
        sdk_result.content = []
        assert _extract_text(sdk_result) == ""

