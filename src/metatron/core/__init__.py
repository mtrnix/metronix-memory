"""Core layer — shared contracts, models, and configuration. Zero external dependencies."""

from metatron.core.config import Settings
from metatron.core.exceptions import (
    AuthenticationError,
    ConnectorError,
    IntegrityError,
    MetatronError,
    RateLimitError,
    SecurityError,
    ToolDisabledError,
    ToolTimeoutError,
)
from metatron.core.models import (
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
    "MetatronError",
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
