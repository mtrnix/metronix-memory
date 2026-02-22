"""MCP Server instance for Metatron.

This module provides the FastMCP server that exposes Metatron's knowledge
base capabilities via the Model Context Protocol.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from mcp.server import FastMCP

# Configure structlog to write to stderr (stdout is reserved for JSON-RPC)
# Set the root logger to WARNING to reduce noise from dependencies
logging.getLogger().setLevel(logging.WARNING)

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
)

logger = structlog.get_logger()


# Create FastMCP server instance
mcp = FastMCP(
    name="MetatronMCP",
    instructions=(
        "MetatronMCP provides access to a team's knowledge base through hybrid search "
        "(vector + BM25 + knowledge graph). Use this server to:\n"
        "- Search the knowledge base with natural language queries\n"
        "- Retrieve specific documents by label\n"
        "- Store new information in the knowledge base\n"
        "- Check system health and workspace status\n"
        "\n"
        "All tools operate within a workspace context. Provide workspace_id when "
        "working with multi-tenant data."
    ),
    log_level="INFO",
    debug=False,
)


def get_server() -> FastMCP:
    """Return the configured FastMCP server instance."""
    return mcp


async def main() -> None:
    """Main entry point for stdio transport."""
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        await mcp.run(
            read_stream,
            write_stream,
            mcp.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
