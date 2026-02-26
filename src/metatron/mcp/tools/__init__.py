"""MCP tool implementations for Metatron.

Importing this package registers all tools with the FastMCP server instance.
Each tool lives in its own module for clarity and the <200 line rule.
"""

from metatron.mcp.tools.search import metatron_search
from metatron.mcp.tools.get import metatron_get
from metatron.mcp.tools.store import metatron_store
from metatron.mcp.tools.status import metatron_status
from metatron.mcp.tools.sync import metatron_sync

__all__ = [
    "metatron_search",
    "metatron_get",
    "metatron_store",
    "metatron_status",
    "metatron_sync",
]
