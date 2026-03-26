"""Abstract base classes — the extension points for enterprise.

Every pluggable component is defined here as an ABC. Core never imports
from upper layers. Upper layers implement these contracts.

Enterprise repo provides alternative implementations
(SAMLAuthBackend, SchemaGuidedProcessor, SAPConnector, etc.)
and registers them via the registry pattern.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from metatron.core.models import (
    Chunk,
    Connection,
    Document,
    OutgoingMessage,
    User,
)


class ConnectorInterface(ABC):
    """Fetches documents from an external data source.

    Each connector handles one source type (Confluence, Jira, etc.).
    Connectors are stateless — configuration comes from Connection objects.

    Lifecycle: configure(connection) → fetch(workspace_id) → documents
    """

    source_role: str = "knowledge_base"

    @abstractmethod
    async def configure(self, connection: Connection, decrypted_config: dict[str, str]) -> None:
        """Initialize the connector with decrypted credentials.

        Args:
            connection: The connection metadata from PostgreSQL.
            decrypted_config: Decrypted JSON config with API tokens, URLs, etc.
        """

    @abstractmethod
    async def fetch(
        self, workspace_id: str, since: datetime | None = None
    ) -> list[Document]:
        """Fetch documents from the source.

        Args:
            workspace_id: Target workspace for document metadata.
            since: If set, only fetch documents modified after this timestamp
                  (incremental sync).

        Returns:
            List of Documents ready for the ingestion pipeline.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Test connectivity to the source. Returns True if reachable."""


class ChannelInterface(ABC):
    """Adapter for a messaging platform (Telegram, Slack, etc.).

    Channels receive messages, route them through the agent, and send
    responses back. Each channel manages its own event loop / webhook.
    """

    @abstractmethod
    async def start(self) -> None:
        """Start listening for messages (polling, webhook, socket mode)."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the channel."""

    @abstractmethod
    async def send(self, message: OutgoingMessage) -> None:
        """Send a message back to the user on this platform.

        Args:
            message: The formatted response to deliver.
        """


class LLMProviderInterface(ABC):
    """Abstraction over LLM backends (Ollama, OpenAI-compatible, etc.).

    Supports both chat completion and embedding generation.
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.1,
    ) -> dict[str, object]:
        """Send a chat completion request.

        Args:
            messages: Conversation history in OpenAI format
                     [{"role": "user", "content": "..."}].
            tools: Optional tool/function definitions for function calling.
            temperature: Sampling temperature.

        Returns:
            Raw response dict with at least "content" and optionally
            "tool_calls" keys.
        """

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: Strings to embed.

        Returns:
            List of embedding vectors (same order as input).
        """


class VectorStoreInterface(ABC):
    """Vector database for storing and searching embeddings.

    Per-workspace collection isolation is enforced at this layer.
    """

    @abstractmethod
    async def ensure_collection(self, workspace_id: str, dim: int) -> None:
        """Create the collection if it doesn't exist.

        Args:
            workspace_id: Used as collection name prefix.
            dim: Embedding dimensionality.
        """

    @abstractmethod
    async def upsert(self, workspace_id: str, chunks: list[Chunk]) -> int:
        """Insert or update chunks with their embeddings.

        Args:
            workspace_id: Target collection.
            chunks: Chunks with populated embedding vectors.

        Returns:
            Number of points upserted.
        """

    @abstractmethod
    async def search_dense(
        self, workspace_id: str, vector: list[float], top_k: int = 20
    ) -> list[tuple[str, float]]:
        """Dense (ANN) vector search.

        Args:
            workspace_id: Collection to search.
            vector: Query embedding.
            top_k: Maximum results.

        Returns:
            List of (chunk_id, score) tuples, descending by score.
        """

    @abstractmethod
    async def search_sparse(
        self, workspace_id: str, query_text: str, top_k: int = 20
    ) -> list[tuple[str, float]]:
        """Sparse (BM25) keyword search.

        Args:
            workspace_id: Collection to search.
            query_text: Raw query string.
            top_k: Maximum results.

        Returns:
            List of (chunk_id, score) tuples, descending by score.
        """


class GraphStoreInterface(ABC):
    """Knowledge graph for entity and relationship storage.

    Backs the graph-enrichment step in retrieval.
    """

    @abstractmethod
    async def add_entities(
        self, workspace_id: str, entities: list[dict[str, str]]
    ) -> int:
        """Create or merge entity nodes.

        Args:
            workspace_id: Workspace scope.
            entities: Dicts with at least "name" and "type" keys.

        Returns:
            Number of entities created or merged.
        """

    @abstractmethod
    async def add_relations(
        self, workspace_id: str, relations: list[dict[str, str]]
    ) -> int:
        """Create relationships between entities.

        Args:
            workspace_id: Workspace scope.
            relations: Dicts with "source", "target", "relation_type" keys.

        Returns:
            Number of relationships created.
        """

    @abstractmethod
    async def query_neighbors(
        self, workspace_id: str, entity_name: str, depth: int = 1
    ) -> list[dict[str, str]]:
        """Find entities connected to the given entity.

        Args:
            workspace_id: Workspace scope.
            entity_name: Starting node name.
            depth: How many hops to traverse.

        Returns:
            List of neighbor dicts with "name", "type", "relation" keys.
        """


class ProcessorInterface(ABC):
    """Transforms raw file content into plain text for chunking.

    One processor per file type (text, PDF, Office docs, etc.).
    """

    @abstractmethod
    def supported_types(self) -> list[str]:
        """Return list of MIME types or extensions this processor handles.

        Example: ["application/pdf", ".pdf"]
        """

    @abstractmethod
    async def extract_text(self, content: bytes, filename: str) -> str:
        """Extract plain text from file content.

        Args:
            content: Raw file bytes.
            filename: Original filename (for extension-based detection).

        Returns:
            Extracted plain text.
        """


class AuthBackendInterface(ABC):
    """Pluggable authentication backend.

    Core provides JWT-based auth. Enterprise can provide SAML, OIDC, etc.
    """

    @abstractmethod
    async def authenticate(self, token: str) -> User | None:
        """Validate a token and return the associated user.

        Args:
            token: Bearer token from the request.

        Returns:
            User if valid, None if invalid/expired.
        """

    @abstractmethod
    async def create_token(self, user: User) -> str:
        """Issue a new token for the given user.

        Args:
            user: The user to create a token for.

        Returns:
            Encoded token string.
        """


class RetrieverInterface(ABC):
    """End-to-end retrieval: query → ranked chunks with context.

    Combines vector search, graph enrichment, and multi-factor scoring.
    """

    @abstractmethod
    async def retrieve(
        self,
        workspace_id: str,
        query: str,
        top_k: int = 10,
    ) -> list[Chunk]:
        """Run the full retrieval pipeline for a query.

        Steps: embed → dense search → sparse search → RRF fusion →
        graph enrichment → multi-factor scoring → context assembly.

        Args:
            workspace_id: Workspace to search in.
            query: User's natural language query.
            top_k: Number of final results.

        Returns:
            Ranked list of Chunks with assembled context.
        """


# ---------------------------------------------------------------------------
# Plugin system protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class EventHandler(Protocol):
    """Async handler for a named event emitted by core.

    Register via ``PluginManager.register_event_handler(event_name, handler)``.
    Handlers must be resilient — unhandled exceptions are caught by EventBus.

    Example::

        async def on_query_executed(event_name: str, payload: dict[str, Any]) -> None:
            log_to_audit_trail(payload["query"], payload["workspace_id"])
    """

    async def __call__(self, event_name: str, payload: dict[str, Any]) -> None:
        """Handle an event.

        Args:
            event_name: Name of the emitted event (e.g. "query_executed").
            payload: Event-specific data dict.
        """
        ...


@runtime_checkable
class PipelineHook(Protocol):
    """Callable hook injected into the search or ingestion pipeline.

    A hook receives a context dict, may enrich or modify it, and must
    return it. Hooks are chained — each hook's output is the next hook's input.

    Register via ``PluginManager.register_pipeline_hook(hook_name, hook)``.

    Example::

        class AuditHook:
            async def __call__(self, context: dict[str, Any]) -> dict[str, Any]:
                context["audit_timestamp"] = datetime.utcnow().isoformat()
                return context
    """

    async def __call__(self, context: dict[str, Any]) -> dict[str, Any]:
        """Process the pipeline context.

        Args:
            context: Mutable pipeline context dict. Contents depend on hook_name.

        Returns:
            The (possibly modified) context dict. Must not return None.
        """
        ...
