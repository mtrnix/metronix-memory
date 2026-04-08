"""Typed exception hierarchy.

Every layer raises only exceptions defined here. No bare exceptions.
Callers can catch at the granularity they need: MetatronError for "anything",
ConnectorError for connector-specific issues, etc.
"""

from __future__ import annotations


class MetatronError(Exception):
    """Base exception for all Metatron errors."""

    def __init__(self, message: str = "", *, details: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ConnectorError(MetatronError):
    """Error from a data-source connector."""


class RateLimitError(ConnectorError):
    """API rate limit hit — caller should retry after delay.

    Attributes:
        retryable: Always True for rate limits.
        retry_after: Seconds to wait before retrying.
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        retry_after: float = 60.0,
        details: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.retryable: bool = True
        self.retry_after: float = retry_after


class AuthenticationError(MetatronError):
    """Invalid or expired credentials."""


class IntegrityError(MetatronError):
    """Data integrity violation (duplicate, constraint, checksum mismatch)."""


class SecurityError(MetatronError):
    """Security policy violation (domain not allowed, command blocked)."""


class ToolDisabledError(MetatronError):
    """Tool invocation blocked because the tool is disabled for this workspace."""


class ToolTimeoutError(MetatronError):
    """Tool execution exceeded the allowed timeout."""


class MemoryError(MetatronError):  # noqa: A001 - intentional shadow of builtin in this namespace
    """Base class for memory subsystem errors (WS1)."""


class MemoryNotFoundError(MemoryError):
    """Requested memory record or snapshot does not exist."""


class SnapshotCorruptError(MemoryError):
    """Snapshot content hash mismatch or unreadable payload."""
