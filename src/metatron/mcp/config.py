"""MCP server configuration model.

Defines the Pydantic model for MCP server connection settings,
stored per-workspace via MCPServerRegistry.
"""

from __future__ import annotations

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
