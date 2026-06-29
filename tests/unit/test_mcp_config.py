"""Tests for metronix.mcp.config — MCP server config and stdio loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metronix.core.config import get_settings
from metronix.mcp.config import (
    MCPServerConfig,
    get_default_workspace_id,
    load_stdio_config,
    resolve_workspace_id,
)


class TestMCPServerConfig:
    def test_minimal_config(self) -> None:
        cfg = MCPServerConfig(name="test", command="echo")
        assert cfg.name == "test"
        assert cfg.command == "echo"
        assert cfg.args == []
        assert cfg.enabled is True

    def test_full_config(self) -> None:
        cfg = MCPServerConfig(
            name="github",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_TOKEN": "abc"},
            workspace_id="ws1",
            enabled=False,
            read_tools=["get_file"],
            description="GitHub MCP",
        )
        assert cfg.workspace_id == "ws1"
        assert cfg.enabled is False
        assert cfg.env["GITHUB_TOKEN"] == "abc"


class TestLoadStdioConfig:
    def test_loads_valid_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"workspace_id": "test-ws"}))
        result = load_stdio_config(config_file)
        assert result["workspace_id"] == "test-ws"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_stdio_config(tmp_path / "nonexistent.json")

    def test_invalid_json_raises(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text("not json {{{")
        with pytest.raises(json.JSONDecodeError):
            load_stdio_config(config_file)


class TestGetDefaultWorkspaceId:
    def test_returns_configured_id(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"workspace_id": "my-ws"}))
        assert get_default_workspace_id(config_file) == "my-ws"

    def test_falls_back_to_server_default_when_missing(self, tmp_path: Path) -> None:
        # Fallback is the server's configured default workspace, not a literal
        # "default" — so MCP-ingested data lands where the REST API / UI look.
        assert (
            get_default_workspace_id(tmp_path / "nope.json") == get_settings().default_workspace_id
        )

    def test_falls_back_to_server_default_when_key_absent(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"other": "value"}))
        assert get_default_workspace_id(config_file) == get_settings().default_workspace_id


class TestResolveWorkspaceId:
    def test_explicit_workspace_wins(self) -> None:
        assert resolve_workspace_id("ws-explicit") == "ws-explicit"

    def test_none_or_empty_defers_to_default(self) -> None:
        # None/empty must resolve to the configured default, never literal "default".
        assert resolve_workspace_id(None) == get_default_workspace_id()
        assert resolve_workspace_id("") == get_default_workspace_id()
