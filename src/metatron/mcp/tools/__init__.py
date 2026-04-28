"""MCP tool implementations for Metatron.

Importing this package registers all tools with the FastMCP server instance.
Each tool lives in its own module for clarity and the <200 line rule.
"""

from metatron.mcp.tools.get import metatron_get
from metatron.mcp.tools.memory_batch_store import metatron_memory_batch_store
from metatron.mcp.tools.memory_context import metatron_memory_get_context
from metatron.mcp.tools.memory_delete import metatron_memory_delete
from metatron.mcp.tools.memory_list import metatron_memory_list
from metatron.mcp.tools.memory_review_list import metatron_memory_review_list
from metatron.mcp.tools.memory_review_resolve import metatron_memory_review_resolve
from metatron.mcp.tools.memory_search import metatron_memory_search
from metatron.mcp.tools.memory_store import metatron_memory_store
from metatron.mcp.tools.memory_update import metatron_memory_update
from metatron.mcp.tools.search import metatron_search
from metatron.mcp.tools.search_fast import metatron_search_fast
from metatron.mcp.tools.status import metatron_status
from metatron.mcp.tools.store import metatron_store
from metatron.mcp.tools.sync import metatron_sync

__all__ = [
    "metatron_search",
    "metatron_search_fast",
    "metatron_get",
    "metatron_store",
    "metatron_status",
    "metatron_sync",
    "metatron_memory_search",
    "metatron_memory_store",
    "metatron_memory_batch_store",
    "metatron_memory_list",
    "metatron_memory_delete",
    "metatron_memory_update",
    "metatron_memory_get_context",
    "metatron_memory_review_list",
    "metatron_memory_review_resolve",
]
