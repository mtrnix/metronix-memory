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
    """Get the default workspace ID from config.

    Returns:
        Workspace ID string, defaults to "default" if not configured.
    """
    try:
        config = load_stdio_config(config_path)
        return config.get("workspace_id", "default")
    except FileNotFoundError:
        return "default"
