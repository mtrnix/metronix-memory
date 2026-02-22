"""MCP server configuration model.

Defines the Pydantic model for MCP server connection settings,
stored per-workspace via MCPServerRegistry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

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
CONFIG_PATH = Path.home() / ".metatron" / "config.json"

# Cached config values
_cached_config: dict[str, Any] | None = None


def load_stdio_config() -> dict[str, Any]:
    """Load workspace configuration from ~/.metatron/config.json.

    This configuration is used by the stdio transport to provide
    workspace context to the MCP server.

    Expected config format:
    {
        "workspace_id": "default",
        "api_key": "optional-api-key",
        "qdrant_url": "http://localhost:6333",
        "memgraph_url": "bolt://localhost:7687"
    }

    Returns:
        Dictionary with configuration values.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        json.JSONDecodeError: If config file is invalid JSON.
    """
    global _cached_config

    if _cached_config is not None:
        return _cached_config

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")

    with open(CONFIG_PATH) as f:
        _cached_config = json.load(f)

    return _cached_config


def get_default_workspace_id() -> str:
    """Get the default workspace ID from config.

    Returns:
        Workspace ID string, defaults to "default" if not configured.
    """
    try:
        config = load_stdio_config()
        return config.get("workspace_id", "default")
    except FileNotFoundError:
        return "default"


def get_api_key() -> Optional[str]:
    """Get the API key from config.

    Returns:
        API key string if configured, None otherwise.
    """
    try:
        config = load_stdio_config()
        return config.get("api_key")
    except FileNotFoundError:
        return None


def get_qdrant_url() -> str:
    """Get the Qdrant URL from config.

    Returns:
        Qdrant URL string, defaults to localhost if not configured.
    """
    try:
        config = load_stdio_config()
        return config.get("qdrant_url", "http://localhost:6333")
    except FileNotFoundError:
        return "http://localhost:6333"


def get_memgraph_url() -> str:
    """Get the Memgraph URL from config.

    Returns:
        Memgraph URL string, defaults to localhost if not configured.
    """
    try:
        config = load_stdio_config()
        return config.get("memgraph_url", "bolt://localhost:7687")
    except FileNotFoundError:
        return "bolt://localhost:7687"


def reload_config() -> dict[str, Any]:
    """Force reload of the configuration file.

    Clears the cache and reloads from disk.

    Returns:
        Reloaded configuration dictionary.
    """
    global _cached_config
    _cached_config = None
    return load_stdio_config()
