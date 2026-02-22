# Stack Research

**Domain:** MCP Server implementation in Python for RAG/knowledge backend integration
**Researched:** 2026-02-22
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **FastMCP** | 3.0.1+ | MCP Server framework | De facto standard — powers 70% of MCP servers, 1M+ daily downloads. Decorator-based API eliminates boilerplate. Auto-generates tool schemas from type hints. |
| **mcp** (official SDK) | 1.26.0+ | Low-level MCP protocol | Official Anthropic SDK. Use directly only if you need fine-grained control over protocol; FastMCP is built on this. |
| **Uvicorn** | 0.34+ | ASGI server | Industry standard for async Python web servers. Required for StreamableHTTP transport in production. |
| **Pydantic** | 2.x | Schema validation | Automatic JSON schema generation for tool inputs/outputs. Already in Metatron's stack. |

### Transport Layer

| Transport | Use Case | Notes |
|-----------|----------|-------|
| **StreamableHTTP** | Production (RECOMMENDED) | Default for remote access. Supports multi-client, horizontal scaling with `stateless_http=True`. Endpoint: `POST /mcp` |
| **stdio** | Local development only | For Claude Desktop / Cursor integration. Not suitable for OpenClaw remote access. |
| **SSE** | DEPRECATED | Do NOT use. Superseded by StreamableHTTP in MCP spec (Nov 2024). |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **starlette** | 0.45+ | ASGI toolkit | Required for custom middleware, CORS, mounting in existing apps. FastMCP uses this internally. |
| **httpx** | 0.28+ | HTTP client | If tools need to call external APIs. Already in Metatron. |
| **uvloop** | 0.21+ | Event loop | Performance boost for Uvicorn. Install with `uvicorn[standard]`. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **MCP Inspector** | Debug MCP servers | `npx -y @modelcontextprotocol/inspector` — browser-based tool for testing tools/resources |
| **uv** | Package management | Recommended by MCP SDK. Faster than pip, handles venv automatically. |

## Installation

```bash
# Core dependencies (add to existing Metatron pyproject.toml)
uv add "fastmcp>=3.0" "uvicorn[standard]>=0.34"

# Or with pip
pip install "fastmcp>=3.0" "uvicorn[standard]>=0.34"

# Development/testing
uv add --dev pytest pytest-asyncio inline-snapshot
```

## Minimal MCP Server Example

```python
# src/metatron/mcp_server/server.py
from fastmcp import FastMCP, Context
from pydantic import BaseModel, Field

mcp = FastMCP(
    "Metatron Knowledge Backend",
    instructions="RAG-powered knowledge search and storage for long-term memory",
    stateless_http=True,  # Required for horizontal scaling
    json_response=True,   # Better for non-streaming tools
)

class SearchResult(BaseModel):
    """Structured search result."""
    chunk_id: str = Field(description="Unique chunk identifier")
    content: str = Field(description="Text content")
    source: str = Field(description="Origin document/source")
    score: float = Field(description="Relevance score 0-1")

@mcp.tool
async def metatron_search(
    query: str,
    workspace_id: str = "default",
    top_k: int = 10,
    ctx: Context = None,
) -> list[SearchResult]:
    """Search the knowledge base using hybrid RAG (dense + BM25 + graph).
    
    Args:
        query: Natural language search query
        workspace_id: Workspace to search within
        top_k: Maximum results to return
    """
    # Import existing search pipeline
    from metatron.retrieval.search import hybrid_search_and_answer
    
    results = await hybrid_search_and_answer(
        workspace_id=workspace_id,
        query=query,
        top_k=top_k,
    )
    return [SearchResult(**r) for r in results]

@mcp.tool
async def metatron_store(
    content: str,
    metadata: dict[str, str] = None,
    workspace_id: str = "default",
) -> str:
    """Store a memory/document in the knowledge base.
    
    Args:
        content: Text content to store
        metadata: Optional metadata (source, tags, etc.)
        workspace_id: Target workspace
    """
    # Implementation using existing ingestion pipeline
    return f"Stored in workspace {workspace_id}"

# Run as HTTP server for remote access
if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

## Production Deployment

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy and install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application
COPY src/ ./src/

# Run with Uvicorn (multiple workers for production)
CMD ["uv", "run", "uvicorn", "metatron.mcp_server.server:mcp.http_app()", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### docker-compose.yml (Full Stack)

```yaml
version: "3.12"
services:
  metatron-mcp:
    build: .
    ports:
      - "8000:8000"
    environment:
      - QDRANT_URL=http://qdrant:6333
      - MEMGRAPH_URL=bolt://memgraph:7687
      - DATABASE_URL=postgresql://user:pass@postgres:5432/metatron
    depends_on:
      - qdrant
      - memgraph
      - postgres

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  memgraph:
    image: memgraph/memgraph:latest
    ports:
      - "7687:7687"
    volumes:
      - memgraph_data:/var/lib/memgraph

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: metatron
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  qdrant_data:
  memgraph_data:
  postgres_data:
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| FastMCP 3.x | Official `mcp` SDK directly | Need low-level protocol control, building custom transport, or contributing to SDK |
| StreamableHTTP | stdio transport | Local-only CLI tools, Claude Desktop integration (not for OpenClaw remote access) |
| FastMCP 3.x | FastAPI + fastapi-mcp | Already have a FastAPI app and want to expose it as MCP. FastMCP 3.x now has native FastAPI integration. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **SSE transport** | Deprecated in MCP spec (Nov 2024). Higher latency, worse scalability. | StreamableHTTP |
| **Stateful HTTP mode** (default) | Sessions stored in memory — breaks behind load balancers. Clients like Cursor don't forward cookies for sticky sessions. | `stateless_http=True` |
| **FastMCP v2** | V3 (Feb 2026) introduced major improvements: component versioning, OAuth support, OpenTelemetry, better ASGI integration. | FastMCP 3.0+ |
| **Flask/Django sync frameworks** | MCP SDK is async-first. Mixing sync/async causes performance issues and event loop errors. | FastAPI/Starlette/Uvicorn |
| **Bare `mcp.run()` for production** | Single worker, no process management, no graceful shutdown. | Uvicorn/Gunicorn with workers |

## Stack Patterns by Variant

**For local development (Claude Desktop/Cursor):**
- Use stdio transport
- Run with `uv run server.py`
- Register in Claude Desktop config

**For production/remote access (OpenClaw integration):**
- Use StreamableHTTP transport
- Set `stateless_http=True` and `json_response=True`
- Deploy behind nginx/traefik with HTTPS
- Run with Uvicorn + 4 workers minimum

**For existing FastAPI app integration:**
- Use FastMCP's `mcp.http_app()` to create ASGI app
- Mount at `/mcp` path in existing Starlette/FastAPI app
- Share lifespan context for database connections

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| FastMCP 3.x | Python 3.10-3.13 | Requires Pydantic 2.x |
| FastMCP 3.x | mcp SDK 1.x | Built on top of official SDK |
| uvicorn[standard] | uvloop 0.21+ | Standard extra includes uvloop, httptools, watchfiles |
| FastMCP 3.x | Starlette 0.45+ | Required for middleware, CORS, custom routes |

## Key Differences: MCP Client vs MCP Server

Metatron already has an **MCP Client** (`src/metatron/mcp/client.py`). The new **MCP Server** is a separate component:

| Aspect | MCP Client (existing) | MCP Server (new) |
|--------|----------------------|------------------|
| Direction | Connects TO external MCP servers | Exposes tools FOR external clients |
| Use case | Sync from Jira/Confluence/Notion MCP servers | Let OpenClaw search/store in Metatron |
| Transport | stdio (subprocess) | StreamableHTTP (network) |
| Package | `mcp` SDK | `fastmcp` (recommended) or `mcp` SDK |

## Sources

- `/modelcontextprotocol/python-sdk` (Context7) — Official MCP Python SDK v1.26.0, FastMCP patterns, transport options
- https://pypi.org/project/mcp/ — Latest version 1.26.0 (Jan 24, 2026)
- https://pypi.org/project/fastmcp/ — FastMCP 3.0.1 (Feb 21, 2026), 1M+ daily downloads
- https://gofastmcp.com/v2/deployment/http — Production HTTP deployment guide, stateless mode, CORS
- https://mcpcat.io/guides/comparing-stdio-sse-streamablehttp/ — Transport comparison, SSE deprecation
- https://mcpplaygroundonline.com/blog/deploy-mcp-server-docker-production-guide — Docker deployment guide

---
*Stack research for: MCP Server + Python RAG backend integration*
*Researched: 2026-02-22*
