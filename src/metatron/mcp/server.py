"""MCP Server instance for Metatron.

This module provides the FastMCP server that exposes Metatron's knowledge
base capabilities via the Model Context Protocol.

Supports dual transport:
- stdio: For local development and direct subprocess invocation
- streamable-http: For HTTP-based clients
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from functools import wraps
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog
from mcp.server import FastMCP
from mcp.server.streamable_http import TransportSecuritySettings

from metatron.activity.context import bind_agent_id, current_agent_id
from metatron.core.events import ERROR_OCCURRED, TOOL_CALLED
from metatron.llm.telemetry import set_telemetry_context

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from metatron.core.events import EventBus

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
# DNS rebinding protection is disabled because Metatron runs behind a reverse
# proxy (nginx/caddy) that sets its own Host header.  Auth is handled by
# METATRON_MCP_API_KEY validation in the middleware instead.
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
    streamable_http_path="/mcp",
    log_level="INFO",
    debug=False,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


# ---------------------------------------------------------------------------
# WS4 S6 — activity logging for MCP tool invocations
# ---------------------------------------------------------------------------

_MAX_ARG_BYTES = 8 * 1024  # 8 KiB
_ACTIVITY_BUS_GETTER: Callable[[], EventBus | None] = lambda: None  # noqa: E731


def set_activity_bus_getter(getter: Callable[[], EventBus | None]) -> None:
    """Inject the EventBus getter. Called from ``api/app.py:create_app()``.

    The MCP tool wrapper reads the bus lazily via this getter — so the
    application factory can install the bus AFTER all tools are registered
    at import time. In standalone stdio/http mode where no factory runs,
    the getter stays as the no-op default and the wrapper becomes a
    pass-through.

    **Call contract:** expected to be invoked exactly once per process, from
    ``create_app()``. Calling it again silently replaces the getter — tests
    and hot-reload paths should reset it back to ``lambda: None`` when they
    are done to avoid cross-test contamination.
    """
    global _ACTIVITY_BUS_GETTER
    _ACTIVITY_BUS_GETTER = getter


def get_activity_bus() -> EventBus | None:
    """Resolve the active EventBus via the lazy getter.

    Used by MCP-side service factories that run outside FastAPI's request
    scope and therefore cannot reach ``request.app.state.plugin_manager``.
    Returns ``None`` in standalone stdio/http mode.
    """
    return _ACTIVITY_BUS_GETTER()


def _project_arguments(
    kwargs: dict[str, Any], *, tool_name: str | None = None
) -> tuple[dict[str, Any], bool]:
    """Serialise tool kwargs, capping payload at 8 KiB.

    Oversized payloads → ``{"__truncated__": True, "preview": "<first 256 chars>"}``.
    Logs a structlog warning when truncation occurs so tool authors can see
    that their payload was capped.
    """
    try:
        serialized = json.dumps(kwargs, default=str)
    except (TypeError, ValueError):
        logger.warning("activity_log.arguments_unserialisable", tool_name=tool_name)
        return {"__unserializable__": True}, True
    payload_size = len(serialized.encode("utf-8"))
    if payload_size <= _MAX_ARG_BYTES:
        try:
            return json.loads(serialized), False
        except Exception:
            logger.warning("activity_log.arguments_unserialisable", tool_name=tool_name)
            return {"__unserializable__": True}, True
    logger.warning(
        "activity_log.arguments_truncated",
        tool_name=tool_name,
        original_size=payload_size,
        cap=_MAX_ARG_BYTES,
    )
    return {"__truncated__": True, "preview": serialized[:256]}, True


def _wrap_tool_with_activity(
    tool_name: str,
    handler: Callable[..., Awaitable[Any]],
    *,
    bus_getter: Callable[[], EventBus | None],
) -> Callable[..., Awaitable[Any]]:
    """Wrap a FastMCP tool coroutine with TOOL_CALLED / ERROR_OCCURRED emission.

    No-ops when ``bus`` is None or ``agent_id`` cannot be resolved.
    """

    @wraps(handler)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        bus = bus_getter()
        start = time.monotonic()
        agent_id = kwargs.get("agent_id") or current_agent_id.get()
        workspace_id = kwargs.get("workspace_id") or ""
        session_id = kwargs.get("session_id")
        arguments, truncated = _project_arguments(kwargs, tool_name=tool_name)

        # Bind agent_id into the contextvar so downstream calls (e.g.
        # `hybrid_search_and_answer`) that read it directly see the same
        # value the wrapper observed — even when the caller passed agent_id
        # only as a kwarg and not as the X-Agent-Id header.
        # Caveat: any background task spawned inside the handler via
        # `asyncio.create_task` will outlive this wrapper's `finally` block,
        # so it will see the contextvar reset to its prior value (likely
        # `None`). No tools currently spawn fire-and-forget tasks; if that
        # changes, propagate `agent_id` explicitly into the spawned task.
        token = bind_agent_id(agent_id) if agent_id is not None else None

        error: BaseException | None = None
        try:
            # Telemetry context wraps the handler — `with` ensures correct
            # __exit__ semantics even if anyone later adds exception-aware
            # cleanup inside set_telemetry_context.
            with set_telemetry_context(
                workspace_id=workspace_id or None,
                agent_id=agent_id,
                source="mcp",
                correlation_id=uuid4(),
            ):
                return await handler(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — emit then re-raise
            error = exc
            raise
        finally:
            if token is not None:
                current_agent_id.reset(token)
            duration_ms = int((time.monotonic() - start) * 1000)
            if bus is not None and agent_id is not None:
                await bus.emit(
                    TOOL_CALLED,
                    {
                        "workspace_id": workspace_id,
                        "agent_id": agent_id,
                        "session_id": session_id,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "arguments_truncated": truncated,
                        "duration_ms": duration_ms,
                        "success": error is None,
                        "error_message": str(error) if error is not None else None,
                    },
                )
                if error is not None:
                    await bus.emit(
                        ERROR_OCCURRED,
                        {
                            "workspace_id": workspace_id,
                            "agent_id": agent_id,
                            "session_id": session_id,
                            "source": "tool",
                            "error_type": type(error).__name__,
                            "error_message": str(error),
                            "context": {"tool_name": tool_name},
                        },
                    )

    return wrapper


# Monkey-patch FastMCP's .tool decorator so every subsequently registered
# tool is wrapped. Tools are registered later via `import metatron.mcp.tools`
# from `api/app.py`; since this module loads first, the patch lands in time.
_original_tool = mcp.tool


def _tool_with_activity(*decorator_args: Any, **decorator_kwargs: Any) -> Any:
    registrar = _original_tool(*decorator_args, **decorator_kwargs)

    def _apply(func: Callable[..., Awaitable[Any]]) -> Any:
        name = decorator_kwargs.get("name") or func.__name__
        # Lazy-resolve the bus getter at call time, not at wrap time. Tools are
        # decorated at module-import time (before create_app() runs), so binding
        # ``_ACTIVITY_BUS_GETTER`` directly would freeze the no-op default into
        # every wrapper closure. Re-reading via globals each invocation lets
        # ``set_activity_bus_getter`` from create_app() take effect.
        wrapped = _wrap_tool_with_activity(name, func, bus_getter=lambda: _ACTIVITY_BUS_GETTER())
        wrapped.__name__ = func.__name__
        wrapped.__qualname__ = getattr(func, "__qualname__", func.__name__)
        return registrar(wrapped)

    return _apply


mcp.tool = _tool_with_activity  # type: ignore[method-assign]


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
    app = mcp.streamable_http_app(
        transport="streamable-http",
        stateless_http=True,
    )

    # WS4 S6 — X-Agent-Id contextvar for standalone MCP transport
    from metatron.api.middleware.agent_id import AgentIdContextMiddleware

    app.add_middleware(AgentIdContextMiddleware)

    # Add authentication middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request  # noqa: TC002
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

    app.add_middleware(AuthMiddleware)

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


async def main(transport: str | None = None) -> None:
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
