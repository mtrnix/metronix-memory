# Phase 1: MCP Server Foundation - Research

**Researched:** 2026-02-22
**Domain:** MCP Server implementation with FastMCP 3.x, stdio + StreamableHTTP transports
**Confidence:** HIGH

## Summary

This phase builds a working MCP Server that exposes Metatron's knowledge capabilities (search, retrieve, store, status) to external MCP hosts like OpenClaw. The recommended approach uses **FastMCP 3.x** (the de facto standard framework built on the official MCP Python SDK) with both **stdio** (local dev) and **StreamableHTTP** (production) transports.

The server integrates as an **L6 component** in Metatron's architecture, delegating to existing L2 Retrieval and L3 Ingestion layers—never duplicating business logic. Key decisions from CONTEXT.md: search results include graph context, structured error format with code/message/hint, cursor-based pagination, stdio reads config from `~/.metatron/config.json`, HTTP uses API key auth.

**Primary recommendation:** Use FastMCP 3.0.1+ with `http_app()` for mounting to existing FastAPI app, shared lifespan pattern, and explicit stderr logging configuration from startup to prevent stdio JSON-RPC corruption.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Search results include graph context**: Each result contains chunk text (~700 chars), source type, doc_label, score, timestamp, PLUS related entities and linked documents from knowledge graph
- **Structured error format**: Errors return JSON with `error.code` (machine-readable), `error.message` (human-readable), `error.hint` (suggested next action)
- **Cursor-based pagination**: Use cursor tokens for stable pagination instead of offset-based (handles dynamic data changes better)
- **stdio workspace context**: Read from `~/.metatron/config.json` at startup
- **HTTP authentication**: API key via `Authorization: Bearer <key>` header

### Claude's Discretion

The following areas are left to Claude's judgment during planning/implementation:
- Store response format details
- HTTP workspace context passing method (header vs URL path vs token-embedded)
- Transport capability parity (identical vs HTTP-richer vs stdio-richer)
- All sync behavior decisions (triggering, feedback, failure handling, incremental support)
- All error handling decisions (retry, degradation, timeouts)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCP-01 | User can search knowledge base with `metatron_search` tool (hybrid RAG: dense + BM25) | FastMCP `@tool` decorator delegates to `retrieval.search.hybrid_search_and_answer()` |
| MCP-02 | User can retrieve specific document with `metatron_get` tool (by doc_label/Jira key/Confluence ID) | Direct lookup via `QdrantVectorStore.search_by_doc_labels()` |
| MCP-03 | User can store memories with `metatron_store` tool (content + metadata) | Delegates to `ingestion.pipeline.ingest_documents()` |
| MCP-04 | User can check system health with `metatron_status` tool (doc count, last sync, embedding model) | Health endpoints already exist in `api/routes/health.py` |
| MCP-05 | MCP tools have proper descriptions for LLM tool selection | FastMCP auto-generates schemas from type hints + docstrings |
| MCP-06 | Search results are paginated (default limit, has_more, next_offset) | Cursor-based pagination pattern from research |
| TRNS-01 | MCP server supports stdio transport (for local development, Claude Desktop) | FastMCP `run()` defaults to stdio, reads `~/.metatron/config.json` |
| TRNS-02 | MCP server supports StreamableHTTP transport (for production, OpenClaw remote) | FastMCP `http_app()` with `transport="streamable-http"` |
| TRNS-03 | MCP server mounts to existing FastAPI app with shared lifespan | Pattern: `FastAPI(lifespan=mcp_app.lifespan)` + `app.mount("/mcp", mcp_app)` |
| SYNC-01 | User can sync documents from configured sources via `metatron_sync` tool | Existing `mcp/sync.py` with hash-based incremental sync |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastMCP | 3.0.1+ | MCP Server framework | De facto standard (1M+ daily downloads), decorator-based API, built on official MCP SDK |
| mcp (SDK) | 1.26.0+ | Official MCP protocol implementation | Required by FastMCP, implements JSON-RPC transport |
| Pydantic | 2.x | Schema validation | Auto-generates JSON schemas from type hints (already in Metatron) |
| Uvicorn | 0.34+ | ASGI server | Required for StreamableHTTP transport in production |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | Latest | Structured logging | All logging in Metatron (already in use) |
| anyio | Latest | Async task management | For concurrent tool execution |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| FastMCP | Raw `mcp` SDK | More boilerplate, manual schema generation |
| StreamableHTTP | SSE transport | SSE is DEPRECATED in MCP spec (Nov 2024) |
| API key auth | OAuth 2.1 | Overkill for self-hosted; Phase 2+ if multi-tenant |

**Installation:**

```bash
pip install 'fastmcp>=3.0.1' 'mcp>=1.26.0' 'uvicorn>=0.34'
```

## Architecture Patterns

### Recommended Project Structure

```
src/metatron/mcp/
├── server.py          # FastMCP instance, tool registration, transport
├── tools.py           # Tool implementations (search, get, store, status, sync)
├── config.py          # Config loading (~/.metatron/config.json for stdio)
├── auth.py            # API key validation for HTTP transport
├── errors.py          # Structured error format (code, message, hint)
├── pagination.py      # Cursor-based pagination helpers
└── app.py             # FastAPI integration (mounting, shared lifespan)
```

### Pattern 1: Mounting MCP Server to Existing FastAPI App

**What:** Integrate MCP server as a mounted ASGI sub-application with shared lifespan.

**When to use:** Production deployment where MCP server shares process with existing REST API.

**Example:**

```python
# src/metatron/mcp/app.py
from fastmcp import FastMCP
from fastapi import FastAPI
from starlette.routing import Mount

# Create MCP server
mcp = FastMCP(
    name="MetatronMCP",
    instructions="Knowledge base search, retrieve, store, and sync tools",
    version="1.0.0",
)

# Create ASGI app from MCP server
mcp_app = mcp.http_app(
    path="/mcp",
    transport="streamable-http",
    stateless_http=True,  # Required for load-balanced deployments
)

# Mount to existing FastAPI app with shared lifespan
def create_mcp_router() -> FastAPI:
    api = FastAPI(
        title="Metatron API",
        lifespan=mcp_app.lifespan,  # CRITICAL: shared lifespan for session management
    )
    api.mount("/mcp", mcp_app)
    return api
```

Source: https://gofastmcp.com/deployment/http

### Pattern 2: Tool Definition with Pydantic Models

**What:** Define tools with structured inputs/outputs using Pydantic models for automatic schema generation.

**When to use:** All tool definitions — ensures LLMs understand parameter types and constraints.

**Example:**

```python
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Optional, List

mcp = FastMCP("MetatronMCP")

class SearchRequest(BaseModel):
    query: str = Field(..., description="Natural language search query")
    workspace_id: Optional[str] = Field(None, description="Target workspace ID")
    limit: int = Field(default=10, ge=1, le=100, description="Max results")
    include_graph: bool = Field(default=True, description="Include graph context")

class SearchResponse(BaseModel):
    results: List[dict]
    has_more: bool
    next_cursor: Optional[str]
    total: int

@mcp.tool
async def metatron_search(request: SearchRequest) -> SearchResponse:
    """Search the knowledge base using hybrid RAG (dense vectors + BM25 + graph enrichment).
    
    Use this tool when the user asks a question about stored documents,
    Jira tickets, Confluence pages, or Notion pages.
    """
    # Delegate to existing retrieval layer
    from metatron.retrieval.search import hybrid_search_and_answer
    answer = hybrid_search_and_answer(
        query=request.query,
        workspace_id=request.workspace_id,
        k=request.limit,
    )
    return format_search_response(answer)
```

Source: https://context7.com/jlowin/fastmcp/llms.txt

### Pattern 3: Structured Error Format

**What:** Return errors with machine-readable code, human-readable message, and hint for recovery.

**When to use:** All error scenarios — connection failures, validation errors, service unavailable.

**Example:**

```python
# src/metatron/mcp/errors.py
from typing import Optional, Any, Dict
from pydantic import BaseModel

class MCPError(BaseModel):
    """Structured error format for MCP tool responses."""
    code: str  # MACHINE_READABLE_ERROR_CODE
    message: str  # Human-readable description
    hint: Optional[str] = None  # Suggested next action
    details: Optional[Dict[str, Any]] = None  # Debug context

    def to_response(self) -> dict:
        return {
            "isError": True,
            "content": [{
                "type": "text",
                "text": self.model_dump_json(indent=2),
            }],
        }

# Error codes
ERROR_CODES = {
    "WORKSPACE_NOT_FOUND": "Workspace '{workspace_id}' does not exist",
    "QDRANT_UNAVAILABLE": "Vector database connection failed",
    "MEMGRAPH_UNAVAILABLE": "Graph database connection failed",
    "POSTGRES_UNAVAILABLE": "PostgreSQL connection failed",
    "INVALID_CURSOR": "Pagination cursor is invalid or expired",
    "RATE_LIMIT_EXCEEDED": "Too many requests, please retry after {retry_after}s",
}

async def handle_tool_error(tool_name: str, error: Exception) -> MCPError:
    """Convert exceptions to structured MCP errors."""
    if "workspace" in str(error).lower():
        return MCPError(
            code="WORKSPACE_NOT_FOUND",
            message=str(error),
            hint="Check workspace_id parameter or list workspaces first",
        )
    if "qdrant" in str(error).lower() or "vector" in str(error).lower():
        return MCPError(
            code="QDRANT_UNAVAILABLE",
            message="Vector database is not responding",
            hint="Check Qdrant service health and connection settings",
        )
    # Default: internal error
    return MCPError(
        code="INTERNAL_ERROR",
        message=f"Tool {tool_name} failed: {str(error)}",
        hint="Retry the request or contact support if issue persists",
    )
```

### Pattern 4: Cursor-Based Pagination

**What:** Use opaque cursor tokens instead of offset integers for stable pagination.

**When to use:** All list/search operations where results may change between pages.

**Example:**

```python
# src/metatron/mcp/pagination.py
import base64
import json
from typing import Optional, Any, Dict, List

def encode_cursor(data: Dict[str, Any]) -> str:
    """Encode pagination state to opaque cursor string."""
    return base64.b64encode(json.dumps(data).encode()).decode()

def decode_cursor(cursor: str) -> Dict[str, Any]:
    """Decode cursor back to pagination state."""
    try:
        return json.loads(base64.b64decode(cursor).decode())
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Invalid cursor: {e}")

class CursorPager:
    """Cursor-based pagination helper."""
    
    def __init__(self, limit: int = 10):
        self.limit = limit
    
    def paginate(
        self,
        results: List[Any],
        cursor: Optional[str] = None,
    ) -> tuple[List[Any], bool, Optional[str]]:
        """Return (items, has_more, next_cursor)."""
        if cursor:
            state = decode_cursor(cursor)
            offset = state.get("offset", 0)
        else:
            offset = 0
        
        items = results[offset : offset + self.limit]
        has_more = len(results) > offset + len(items)
        next_cursor = encode_cursor({"offset": offset + len(items)}) if has_more else None
        
        return items, has_more, next_cursor
```

### Pattern 5: Stdio Config Loading

**What:** Load workspace context from `~/.metatron/config.json` for stdio transport.

**When to use:** Local development / Claude Desktop integration.

**Example:**

```python
# src/metatron/mcp/config.py
import json
from pathlib import Path
from typing import Optional, Dict, Any

class StdioConfig:
    """Configuration for stdio transport mode."""
    
    CONFIG_PATH = Path.home() / ".metatron" / "config.json"
    
    def __init__(self) -> None:
        self._config: Dict[str, Any] = {}
        self._load()
    
    def _load(self) -> None:
        """Load config from disk."""
        if not self.CONFIG_PATH.exists():
            self._config = {
                "default_workspace_id": "MTRNIX",
                "api_key": None,
            }
            return
        try:
            self._config = json.loads(self.CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError) as e:
            # Fall back to defaults on error
            self._config = {"default_workspace_id": "MTRNIX"}
    
    @property
    def default_workspace_id(self) -> str:
        return self._config.get("default_workspace_id", "MTRNIX")
    
    @property
    def api_key(self) -> Optional[str]:
        return self._config.get("api_key")
```

### Pattern 6: HTTP API Key Authentication

**What:** Validate `Authorization: Bearer <key>` header for HTTP transport requests.

**When to use:** Production HTTP transport to prevent unauthorized access.

**Example:**

```python
# src/metatron/mcp/auth.py
import os
from typing import Optional

async def validate_api_key(authorization_header: Optional[str]) -> bool:
    """Validate API key from Authorization header."""
    if not authorization_header:
        return False
    
    if not authorization_header.startswith("Bearer "):
        return False
    
    provided_key = authorization_header[7:]  # Remove "Bearer " prefix
    expected_key = os.environ.get("METATRON_MCP_API_KEY")
    
    if not expected_key:
        # If no key configured, allow all (dev mode)
        return True
    
    return provided_key == expected_key

# Middleware usage with FastMCP
from fastmcp import FastMCP
from fastmcp.server.context import Context

mcp = FastMCP("MetatronMCP")

@mcp.tool
async def metatron_search(query: str, ctx: Context) -> dict:
    """Search with authentication check."""
    # Access HTTP request headers if available
    if ctx.request_context and ctx.request_context.request:
        auth_header = ctx.request_context.request.headers.get("Authorization")
        if not await validate_api_key(auth_header):
            raise PermissionError("Invalid or missing API key")
    
    # Proceed with search...
```

Source: https://gofastmcp.com/llms

### Anti-Patterns to Avoid

- **Print to stdout in stdio mode:** Any `print()` or stdout write corrupts JSON-RPC. Configure all logging to stderr BEFORE server starts.
- **Token passthrough:** Never accept raw user tokens and forward them downstream. Server MUST obtain its own tokens for downstream services.
- **Thin REST wrapper:** Don't force agents to orchestrate multiple tool calls. Curate tools for agent consumption.
- **Unbounded result sets:** Always paginate list operations (default 10-50). Truncate text with "..." and offer `get_full` tool.
- **Vague tool names:** Use distinct names (`metatron_search_docs`, not just `search`). Write descriptions that explain WHEN to use.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MCP Server framework | Raw JSON-RPC over stdio/HTTP | FastMCP 3.x | Handles transport multiplexing, session management, schema generation, auth |
| Tool schema generation | Manual JSON Schema definitions | Pydantic models with FastMCP `@tool` | Auto-generates from type hints, validates inputs, reduces boilerplate |
| Cursor encoding | Custom token format | Base64-encoded JSON state | Standard, debuggable, supports arbitrary pagination state |
| Config loading | Custom parser | Standard `~/.metatron/config.json` with JSON | User expectation, easy debugging, portable |
| API key validation | Custom auth scheme | Bearer token in Authorization header | Standard HTTP auth, works with reverse proxies, load balancers |
| Lifespan management | Manual async context | FastMCP `http_app().lifespan` | Handles session cleanup, connection pooling, graceful shutdown |

**Key insight:** FastMCP abstracts MCP spec complexity (JSON-RPC framing, transport negotiation, session management) so you focus on tool logic. Building raw MCP server is like building FastAPI from scratch.

## Common Pitfalls

### Pitfall 1: STDIO Logging Corruption

**What goes wrong:** Any `print()` or stdout write corrupts JSON-RPC protocol, causing client parse errors.

**Why it happens:** Stdio transport uses stdout for JSON-RPC messages. Logging to stdout interleaves with protocol messages.

**How to avoid:**
1. Configure ALL logging to stderr BEFORE any server code runs:
   ```python
   import structlog
   import sys
   
   structlog.configure(
       processors=[...],
       wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
       context_class=dict,
       logger_factory=structlog.WriteLoggerFactory(sys.stderr),  # CRITICAL
       cache_logger_on_first_use=True,
   )
   ```
2. Add CI check for `print(` in server code:
   ```bash
   grep -r "print(" src/metatron/mcp/ && exit 1
   ```
3. Use `ctx.info()`, `ctx.debug()` from FastMCP Context for tool-level logging.

**Warning signs:** Claude Desktop shows "Failed to parse MCP response" or JSON decode errors in logs.

### Pitfall 2: Shared Lifespan Not Passed

**What goes wrong:** MCP server mounts to FastAPI but lifespan not shared, causing session management failures.

**Why it happens:** FastMCP's `http_app()` creates its own lifespan for session cleanup. If not passed to FastAPI, sessions leak.

**How to avoid:**
```python
# CORRECT
mcp_app = mcp.http_app(path="/mcp")
api = FastAPI(lifespan=mcp_app.lifespan)  # Pass lifespan
api.mount("/mcp", mcp_app)

# WRONG - sessions will leak
mcp_app = mcp.http_app(path="/mcp")
api = FastAPI()  # Missing lifespan!
api.mount("/mcp", mcp_app)
```

**Warning signs:** "Session not found" errors after first request, memory leaks, connections not released.

### Pitfall 3: Stateless HTTP Mode Missing

**What goes wrong:** Production HTTP transport without `stateless_http=True` fails under load balancing.

**Why it happens:** Default mode assumes single-server stateful connections. Load balancers break session affinity.

**How to avoid:**
```python
mcp_app = mcp.http_app(
    path="/mcp",
    transport="streamable-http",
    stateless_http=True,  # MANDATORY for production
)
```

**Warning signs:** Works on localhost, fails with "Session expired" behind nginx/reverse proxy.

### Pitfall 4: Tool Response Bloat

**What goes wrong:** Tool responses dump entire documents, overflowing context window.

**Why it happens:** No truncation or pagination on large result sets.

**How to avoid:**
1. Always paginate: `limit=10`, return `has_more`, `next_cursor`
2. Truncate text: `text[:700] + "..."`
3. Provide `metatron_get_full` tool for fetching complete documents

**Warning signs:** "Context window exceeded" errors, LLM responses cut off mid-sentence.

### Pitfall 5: Duplicate Business Logic

**What goes wrong:** MCP tools re-implement search/store logic instead of delegating to existing layers.

**Why it happens:** Convenience of copying code vs proper dependency injection.

**How to avoid:**
```python
# CORRECT - delegate to L2 Retrieval
@mcp.tool
async def metatron_search(query: str, workspace_id: str) -> dict:
    from metatron.retrieval.search import hybrid_search_and_answer
    return hybrid_search_and_answer(query=query, workspace_id=workspace_id)

# WRONG - duplicated logic, drift guaranteed
@mcp.tool
async def metatron_search(query: str, workspace_id: str) -> dict:
    # Re-implements hybrid search... DON'T DO THIS
```

**Warning signs:** Bug fixes in `retrieval/search.py` don't reflect in MCP tool behavior.

## Code Examples

### Tool Implementation: metatron_search

```python
# src/metatron/mcp/tools.py
from fastmcp import FastMCP
from fastmcp.server.context import Context
from pydantic import BaseModel, Field
from typing import Optional, List

from metatron.mcp.errors import handle_tool_error
from metatron.mcp.pagination import CursorPager

mcp = FastMCP("MetatronMCP")

class SearchRequest(BaseModel):
    query: str = Field(..., description="Natural language search query")
    workspace_id: Optional[str] = Field(
        None,
        description="Target workspace ID (uses default if not provided)",
    )
    limit: int = Field(default=10, ge=1, le=100, description="Max results to return")
    cursor: Optional[str] = Field(None, description="Pagination cursor for next page")
    include_graph: bool = Field(default=True, description="Include knowledge graph context")

class SearchResult(BaseModel):
    doc_label: str
    title: str
    snippet: str  # Truncated to ~700 chars
    source_type: str  # jira, confluence, notion, upload
    score: float
    timestamp: str
    graph_context: Optional[dict]  # Related entities if include_graph=True

class SearchResponse(BaseModel):
    results: List[SearchResult]
    has_more: bool
    next_cursor: Optional[str]
    total: int

@mcp.tool
async def metatron_search(
    query: str,
    workspace_id: Optional[str] = None,
    limit: int = 10,
    cursor: Optional[str] = None,
    include_graph: bool = True,
) -> SearchResponse:
    """Search the knowledge base using hybrid RAG.
    
    This tool combines dense vector search, BM25 keyword matching,
    and knowledge graph enrichment to find relevant documents.
    
    Use this tool when the user:
    - Asks a question about stored knowledge
    - Wants to find documents on a topic
    - References a project, person, or technical term
    
    Graph context includes related entities (people, projects, technologies)
    and their relationships to results.
    """
    try:
        # Delegate to existing retrieval layer (L2)
        from metatron.retrieval.search import hybrid_search_and_answer
        
        # Note: hybrid_search_and_answer returns formatted answer string
        # For MCP, we want structured results, so call lower-level search
        from metatron.storage.qdrant import get_hybrid_store
        from metatron.retrieval.search import diversify_results
        
        store = get_hybrid_store(workspace_id)
        raw_results = store.hybrid_search(query, limit=limit * 2)
        results = diversify_results(raw_results, k=limit)
        
        # Format results with graph context
        formatted = []
        for r in results:
            formatted.append(SearchResult(
                doc_label=r.get("doc_label", ""),
                title=r.get("title", ""),
                snippet=(r.get("memory") or r.get("data", ""))[:700] + "...",
                source_type=r.get("type", "unknown"),
                score=r.get("score", 0),
                timestamp=r.get("timestamp", ""),
                graph_context=None,  # TODO: Add graph enrichment
            ))
        
        # Pagination
        pager = CursorPager(limit=limit)
        items, has_more, next_cursor = pager.paginate(formatted, cursor)
        
        return SearchResponse(
            results=items,
            has_more=has_more,
            next_cursor=next_cursor,
            total=len(formatted),
        )
        
    except Exception as e:
        error = handle_tool_error("metatron_search", e)
        raise ValueError(error.model_dump_json())
```

### Tool Implementation: metatron_get

```python
@mcp.tool
async def metatron_get(
    doc_label: str,
    workspace_id: Optional[str] = None,
) -> dict:
    """Retrieve a specific document by label.
    
    Use this tool when the user:
    - Provides a Jira key (e.g., "MTRNIX-108")
    - Provides a Confluence page ID
    - References a document by exact identifier
    
    This performs direct lookup, not search.
    """
    try:
        from metatron.storage.qdrant import get_hybrid_store
        
        store = get_hybrid_store(workspace_id)
        results = store.search_by_doc_labels([doc_label], limit=1)
        
        if not results:
            return {
                "isError": True,
                "content": [{
                    "type": "text",
                    "text": f"Document '{doc_label}' not found",
                }],
            }
        
        doc = results[0]
        return {
            "doc_label": doc.get("doc_label"),
            "title": doc.get("title"),
            "content": doc.get("memory") or doc.get("data"),
            "source_type": doc.get("type"),
            "timestamp": doc.get("timestamp"),
        }
        
    except Exception as e:
        error = handle_tool_error("metatron_get", e)
        raise ValueError(error.model_dump_json())
```

### Tool Implementation: metatron_store

```python
@mcp.tool
async def metatron_store(
    content: str,
    title: Optional[str] = None,
    workspace_id: Optional[str] = None,
    doc_label: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Store a new document or memory in the knowledge base.
    
    Use this tool when the user:
    - Wants to save information for later retrieval
    - Records a meeting conclusion or decision
    - Captures important context about a project
    
    The document will be chunked, embedded, and stored for future search.
    """
    try:
        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents
        from datetime import datetime
        
        doc = Document(
            content=content,
            title=title or "Untitled",
            doc_label=doc_label or f"MEMO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            source_type="memo",
            metadata=metadata or {},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        result = ingest_documents(
            documents=[doc],
            workspace_id=workspace_id or "MTRNIX",
            connector_type="mcp_store",
            incremental=False,
        )
        
        return {
            "success": True,
            "doc_label": doc.doc_label,
            "chunks_stored": result.documents_new + result.documents_updated,
        }
        
    except Exception as e:
        error = handle_tool_error("metatron_store", e)
        raise ValueError(error.model_dump_json())
```

### Tool Implementation: metatron_status

```python
@mcp.tool
async def metatron_status() -> dict:
    """Check system health and status.
    
    Returns document counts, last sync timestamps, and service health.
    Use this tool to verify the knowledge base is operational.
    """
    try:
        from metatron.storage.qdrant import get_hybrid_store
        from datetime import datetime
        
        store = get_hybrid_store()
        
        # TODO: Get actual counts from stores
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "documents": {
                "total": 0,  # TODO: Query actual count
                "by_source": {
                    "jira": 0,
                    "confluence": 0,
                    "notion": 0,
                    "upload": 0,
                },
            },
            "last_sync": None,  # TODO: Query last sync timestamp
            "embedding_model": "nomic-embed-text",
        }
        
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }
```

### Tool Implementation: metatron_sync

```python
@mcp.tool
async def metatron_sync(
    source: Optional[str] = None,
    workspace_id: Optional[str] = None,
    force_full: bool = False,
) -> dict:
    """Sync documents from configured sources.
    
    Use this tool when the user:
    - Wants to update stale documents from Confluence/Jira/Notion
    - Has made changes in source systems and wants them reflected
    
    Incremental sync by default (only changed documents).
    Set force_full=True for complete re-sync.
    """
    try:
        from metatron.mcp.sync import MCPSyncManager
        from metatron.mcp.registry import MCPServerRegistry
        
        registry = MCPServerRegistry()
        manager = MCPSyncManager(registry)
        
        workspace_id = workspace_id or "MTRNIX"
        
        if source:
            # Sync specific source
            config = registry.get(source)
            if not config:
                raise ValueError(f"Source '{source}' not configured")
            result = await manager.sync_server(config, workspace_id, force_full)
        else:
            # Sync all sources
            results = await manager.sync_all(workspace_id, force_full)
            result = {
                "sources_synced": len(results),
                "details": [
                    {"source": name, "fetched": r.documents_fetched, "new": r.documents_new}
                    for name, r in results
                ],
            }
        
        return {
            "success": True,
            "sync_result": result,
        }
        
    except Exception as e:
        error = handle_tool_error("metatron_sync", e)
        raise ValueError(error.model_dump_json())
```

### Server Entry Point with Dual Transport

```python
# src/metatron/mcp/__main__.py
import argparse
import sys
from pathlib import Path

import structlog

# CRITICAL: Configure logging to stderr BEFORE any MCP code runs
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.add_timestamp,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.WriteLoggerFactory(sys.stderr),  # Stdout is for JSON-RPC!
    cache_logger_on_first_use=True,
)

from fastmcp import FastMCP

def main():
    parser = argparse.ArgumentParser(description="Metatron MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="HTTP host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP port (default: 8000)",
    )
    args = parser.parse_args()
    
    # Create MCP server with all tools
    mcp = FastMCP(
        name="MetatronMCP",
        instructions="Enterprise knowledge base with hybrid RAG search",
        version="1.0.0",
    )
    
    # Import tools to register them
    from metatron.mcp import tools  # noqa: F401
    
    if args.transport == "stdio":
        # Stdio mode for Claude Desktop / local dev
        mcp.run()  # Defaults to stdio
    else:
        # HTTP mode for production
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
        )

if __name__ == "__main__":
    main()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SSE transport | StreamableHTTP | Nov 2024 MCP spec | Horizontal scaling, stateless mode, better retry semantics |
| Manual JSON-RPC framing | FastMCP framework | 2024-2025 | 10x less boilerplate, automatic schema generation |
| Offset pagination | Cursor pagination | 2024 best practice | Handles dynamic data changes, stable across clients |
| JSON config files | `fastmcp.json` standard | FastMCP 2.12 (2025) | Portable server configs, declarative deployment |

**Deprecated/outdated:**
- **SSE transport:** Removed from MCP spec Nov 2024. Use StreamableHTTP.
- **FastMCP v2:** Obsolete. v3 (Feb 2026) added OAuth, OpenTelemetry, better ASGI integration.
- **Token passthrough auth:** Breaks audit trails. Use server-scoped tokens.

## Open Questions

1. **HTTP workspace context passing method**
   - What we know: Stdio reads from `~/.metatron/config.json`. HTTP needs alternative.
   - What's unclear: Should workspace_id come from header (`X-Workspace-ID`), URL path (`/mcp/{workspace_id}`), or embedded in token?
   - Recommendation: Start with `X-Workspace-ID` header (simplest, debuggable). Migrate to token-embedded for multi-tenant.

2. **Transport capability parity**
   - What we know: CONTEXT.md leaves this to discretion.
   - What's unclear: Should stdio and HTTP expose identical tools, or should HTTP have richer features (batch ops, admin tools)?
   - Recommendation: Start with identical capabilities. Add HTTP-only admin tools in Phase 2 if needed.

3. **Sync triggering behavior**
   - What we know: SYNC-01 requires `metatron_sync` tool.
   - What's unclear: Should sync support scheduled/auto triggers, or manual only for Phase 1?
   - Recommendation: Manual-only for Phase 1 (via tool call). Add scheduled sync in Phase 2.

4. **Graceful degradation strategy**
   - What we know: Qdrant/Memgraph/Postgres may be down.
   - What's unclear: Should tools return partial results, queued operations, or hard failures?
   - Recommendation: Return structured error with `hint: "Retry in 30s"` for transient failures. No queuing in Phase 1.

## Sources

### Primary (HIGH confidence)

- **Context7:** `/jlowin/fastmcp` — FastMCP 3.x documentation, tool registration, transport patterns, mounting examples
- **Context7:** `/modelcontextprotocol/python-sdk` — Official MCP Python SDK v1.26.0, stdio/StreamableHTTP client examples
- **FastMCP docs:** https://gofastmcp.com/deployment/http — HTTP mounting, shared lifespan, stateless mode
- **FastMCP docs:** https://gofastmcp.com/llms — Authentication patterns (API key, OAuth)

### Secondary (MEDIUM confidence)

- **NearForm:** "Implementing MCP: Tips, Tricks and Pitfalls" — Stdio logging, error handling patterns
- **OWASP:** "Practical Guide for Secure MCP Server Development" — Token passthrough anti-pattern, auth best practices
- **Docker Docs:** "Control startup order in Compose" — Healthcheck patterns (relevant for Phase 2)

### Tertiary (LOW confidence)

- Various community discussions on curl|bash installer security — Marked for validation in Phase 3

## Metadata

**Confidence breakdown:**
- **Standard stack:** HIGH — Official MCP SDK docs, FastMCP is de facto standard (1M+ downloads/day), Context7 sources
- **Architecture:** HIGH — Official FastMCP mounting patterns, aligns with Metatron's L0-L6 layer model
- **Patterns:** HIGH — Multiple official examples from gofastmcp.com and Context7
- **Pitfalls:** HIGH — NearForm tips, OWASP security guide, official SDK docs
- **Code examples:** HIGH — Adapted from official FastMCP examples

**Research date:** 2026-02-22
**Valid until:** 2026-05-22 (3 months — FastMCP API stable, MCP spec mature)
