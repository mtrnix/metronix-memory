"""Core layer — shared contracts, models, and configuration. Zero external dependencies."""

from metronix.core.config import Settings
from metronix.core.exceptions import (
    AuthenticationError,
    ConnectorError,
    IntegrityError,
    MetronixError,
    RateLimitError,
    SecurityError,
    ToolDisabledError,
    ToolTimeoutError,
)
from metronix.core.models import (
    Chunk,
    ChunkType,
    Connection,
    Document,
    FileRecord,
    IncomingMessage,
    OutgoingMessage,
    QueryStep,
    Role,
    Skill,
    SyncResult,
    User,
    Workspace,
)

__all__ = [
    "Settings",
    "AuthenticationError",
    "ConnectorError",
    "IntegrityError",
    "MetronixError",
    "RateLimitError",
    "SecurityError",
    "ToolDisabledError",
    "ToolTimeoutError",
    "Chunk",
    "ChunkType",
    "Connection",
    "Document",
    "FileRecord",
    "IncomingMessage",
    "OutgoingMessage",
    "QueryStep",
    "Role",
    "Skill",
    "SyncResult",
    "User",
    "Workspace",
]
