"""Entry point for running the MCP server as a module.

Usage:
    python -m metatron.mcp --transport stdio
    python -m metatron.mcp --transport streamable-http --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# Configure logging to stderr BEFORE any MCP code
# This is CRITICAL - stdout is reserved for JSON-RPC communication
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

# Now import MCP server - structlog is configured in server.py
from metatron.mcp.server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    TRANSPORT_HTTP,
    TRANSPORT_STDIO,
    main,
)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for MCP server."""
    parser = argparse.ArgumentParser(
        description="Metatron MCP Server - Knowledge base via Model Context Protocol"
    )
    parser.add_argument(
        "--transport",
        choices=[TRANSPORT_STDIO, TRANSPORT_HTTP],
        default=TRANSPORT_STDIO,
        help="Transport type (stdio or streamable-http)",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"HTTP host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"HTTP port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for the MCP server."""
    args = parse_args()

    # Update logging level if debug is enabled
    if args.debug:
        logging.getLogger().setLevel(logging.INFO)

    # Run the server
    asyncio.run(_run_server(args))


async def _run_server(args: argparse.Namespace) -> None:
    """Run the MCP server with the specified transport.

    Args:
        args: Parsed command line arguments
    """
    if args.transport == TRANSPORT_HTTP:
        from metatron.mcp.server import run_http

        await run_http(args.host, args.port)
    else:
        from metatron.mcp.server import run_stdio

        await run_stdio()


if __name__ == "__main__":
    main()
