"""Entry point for running the MCP server as a module.

Usage:
    python -m metronix.mcp --transport stdio
    python -m metronix.mcp --transport streamable-http --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

# Configure logging to stderr BEFORE any MCP code
# This is CRITICAL — stdout is reserved for JSON-RPC communication
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)

# Import MCP server (structlog is configured in server.py)
# Import tools so their @mcp.tool() decorators register
import metronix.mcp.tools  # noqa: E402, F401
from metronix.mcp.server import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_PORT,
    TRANSPORT_HTTP,
    TRANSPORT_STDIO,
)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for MCP server."""
    parser = argparse.ArgumentParser(
        description="Metronix MCP Server — Knowledge base via Model Context Protocol",
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


def cli_main() -> None:
    """Entry point for the MCP server CLI."""
    args = parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.INFO)

    asyncio.run(_run_server(args))


async def _run_server(args: argparse.Namespace) -> None:
    """Run the MCP server with the specified transport."""
    if args.transport == TRANSPORT_HTTP:
        from metronix.mcp.server import run_http

        await run_http(args.host, args.port)
    else:
        from metronix.mcp.server import run_stdio

        await run_stdio()


if __name__ == "__main__":
    cli_main()
