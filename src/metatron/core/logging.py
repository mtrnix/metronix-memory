"""Structured logging setup using structlog.

All modules use: logger = structlog.get_logger()
Call configure_logging() once at startup.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog with JSON or console output.

    Args:
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        json_output: If True, emit JSON lines. If False, use colored console output.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Silence noisy third-party loggers
    for noisy in ("neo4j", "discord", "httpcore", "httpx", "hpack", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def bind_context(workspace_id: str = "", trace_id: str = "") -> None:
    """Bind workspace_id and trace_id to the current context.

    These will be included in all subsequent log entries from this
    async context (uses contextvars under the hood).

    Args:
        workspace_id: Current workspace scope.
        trace_id: Current query trace ID.
    """
    ctx: dict[str, str] = {}
    if workspace_id:
        ctx["workspace_id"] = workspace_id
    if trace_id:
        ctx["trace_id"] = trace_id
    if ctx:
        structlog.contextvars.bind_contextvars(**ctx)
