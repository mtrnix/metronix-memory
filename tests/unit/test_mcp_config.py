"""Tests for metronix.mcp.config — MCP server config and stdio loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from metronix.mcp.config import (
    MCPServerConfig,
    get_default_workspace_id,
    load_stdio_config,
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

    def test_returns_default_when_missing(self, tmp_path: Path) -> None:
        assert get_default_workspace_id(tmp_path / "nope.json") == "default"

    def test_returns_default_when_key_absent(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"other": "value"}))
        assert get_default_workspace_id(config_file) == "default"
