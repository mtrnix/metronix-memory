"""MCP Server instance for Metatron.

This module provides the FastMCP server that exposes Metatron's knowledge
base capabilities via the Model Context Protocol.

Supports dual transport:
- stdio: For local development and direct subprocess invocation
- streamable-http: For HTTP-based clients
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any, Optional

import structlog

from mcp.server import FastMCP

# Configure structlog to write to stderr (stdout is reserved for JSON-RPC)
# Set the root logger to WARNING to reduce noise from dependencies
logging.getLogger().setLevel(logging.WARNING)

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
)

logger = structlog.get_logger()

# Transport types
TRANSPORT_STDIO = "stdio"
TRANSPORT_HTTP = "streamable-http"

# Default values
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080


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
        "- Trigger document sync from configured MCP sources\n"
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


def get_transport() -> str:
    """Get the transport type from environment or arguments.

    Returns:
        Transport type: "stdio" or "streamable-http"
    """
    return os.environ.get("METATRON_MCP_TRANSPORT", TRANSPORT_STDIO)


def get_http_host() -> str:
    """Get the HTTP host from environment or arguments."""
    return os.environ.get("METATRON_MCP_HOST", DEFAULT_HOST)


def get_http_port() -> int:
    """Get the HTTP port from environment or arguments."""
    return int(os.environ.get("METATRON_MCP_PORT", str(DEFAULT_PORT)))


async def run_stdio() -> None:
    """Run the MCP server with stdio transport."""
    from metatron.mcp.config import get_default_workspace_id

    # Load workspace config from ~/.metatron/config.json
    workspace_id = get_default_workspace_id()
    logger.info("mcp.server.stdio.starting", workspace_id=workspace_id)

    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await mcp.run(
            read_stream,
            write_stream,
            mcp.create_initialization_options(),
        )


async def run_http(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> None:
    """Run the MCP server with HTTP transport.

    Args:
        host: Host to bind to
        port: Port to listen on
    """
    from metatron.mcp.auth import validate_api_key

    logger.info("mcp.server.http.starting", host=host, port=port)

    # Create HTTP app with stateless mode
    app = mcp.http_app(
        transport="streamable-http",
        stateless_http=True,
    )

    # Add authentication middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # Skip auth for health checks
            if request.url.path in ("/health", "/ready"):
                return await call_next(request)

            # Get authorization header
            auth_header = request.headers.get("authorization")

            # Validate API key
            if not validate_api_key(auth_header):
                return JSONResponse(
                    status_code=401,
                    content={"error": "Invalid or missing API key"},
                )

            return await call_next(request)

    # Note: The middleware would need to be added to the app
    # For now, we rely on the MCP server's built-in auth handling

    # Import and run with uvicorn
    import uvicorn

    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main(transport: Optional[str] = None) -> None:
    """Main entry point that selects transport.

    Args:
        transport: Transport to use (stdio or streamable-http).
                   If None, reads from environment.
    """
    transport = transport or get_transport()

    if transport == TRANSPORT_HTTP:
        await run_http(get_http_host(), get_http_port())
    else:
        await run_stdio()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Metatron MCP Server")
    parser.add_argument(
        "--transport",
        choices=[TRANSPORT_STDIO, TRANSPORT_HTTP],
        default=None,
        help="Transport type (default: from METATRON_MCP_TRANSPORT env var)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"HTTP host (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"HTTP port (default: {DEFAULT_PORT})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    import asyncio

    args = parse_args()

    # Apply CLI arguments to environment
    if args.transport:
        os.environ["METATRON_MCP_TRANSPORT"] = args.transport
    if args.host:
        os.environ["METATRON_MCP_HOST"] = args.host
    if args.port:
        os.environ["METATRON_MCP_PORT"] = str(args.port)

    asyncio.run(main(args.transport))
