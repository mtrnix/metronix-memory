"""MCP server configuration model.

Defines the Pydantic model for MCP server connection settings,
stored per-workspace via MCPServerRegistry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server connection.

    Each server is launched as a stdio subprocess. The command + args
    define how to start it; env provides extra environment variables.

    Attributes:
        name: Human-readable server name (e.g., "github-mcp").
        command: Executable to launch (e.g., "npx", "uvx", "python").
        args: Arguments for the command (e.g., ["-y", "@modelcontextprotocol/server-github"]).
        env: Extra environment variables to pass to the subprocess.
        workspace_id: Workspace this server belongs to.
        enabled: Whether to include this server in sync operations.
        read_tools: Tool names to use for fetching data (auto-detected if empty).
        description: Optional human description of what this server provides.
    """

    model_config = ConfigDict(frozen=False)

    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    workspace_id: str = ""
    enabled: bool = True
    read_tools: list[str] = Field(default_factory=list)
    write_tools: list[str] = Field(default_factory=list)
    list_tool: str = ""
    get_tool: str = ""
    description: str = ""


# --- Stdio Config Loader ---

# Default path for stdio transport configuration
CONFIG_PATH = Path.home() / ".metronix" / "config.json"


def load_stdio_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load workspace configuration from ~/.metronix/config.json.

    Args:
        config_path: Path to config file (injectable for testing).

    Returns:
        Dictionary with configuration values.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        json.JSONDecodeError: If config file is invalid JSON.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path) as f:
        return json.load(f)


def get_default_workspace_id(config_path: Path = CONFIG_PATH) -> str:
    """Get the default workspace ID for MCP calls.

    Resolution order: the MCP stdio config file's ``workspace_id``, then the
    server's configured ``DEFAULT_WORKSPACE_ID``. The latter is the same default
    the REST API and UI use, so MCP-ingested data and memory land in that
    workspace instead of a stray literal ``"default"`` workspace the UI never
    shows.
    """
    from metronix.core.config import get_settings

    fallback = get_settings().default_workspace_id
    try:
        config = load_stdio_config(config_path)
        return config.get("workspace_id") or fallback
    except FileNotFoundError:
        return fallback


def resolve_workspace_id(workspace_id: str | None) -> str:
    """Resolve an explicit ``workspace_id``, falling back to the configured default.

    MCP tools call this so an omitted ``workspace_id`` routes to the server's
    ``DEFAULT_WORKSPACE_ID`` rather than a literal ``"default"`` — keeping
    MCP-driven ingestion/memory in the same workspace as the REST API and UI.
    """
    return workspace_id or get_default_workspace_id()
