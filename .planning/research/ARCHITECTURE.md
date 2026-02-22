# Architecture Research

**Domain:** MCP Server Integration with Python Layered RAG/Agent Systems
**Researched:** 2026-02-22
**Confidence:** HIGH (Context7 official docs, official Python SDK, multiple verified sources)

## Recommended Architecture

### System Overview

MCP Server integration fits naturally as a **new L6 component** that exposes Metatron's capabilities externally while respecting the existing layer boundaries.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ L6: API + MCP SERVER (NEW)                                              │
│     FastAPI routes  │  MCP Server (tools, resources, prompts)           │
│     ↑ both mount to same ASGI app, share lifespan                       │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L5: CHANNELS                                                            │
│     Telegram, Discord, Slack bots                                       │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L4: AGENT                                                               │
│     Router, orchestration, conversation management                      │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L3: DOMAIN SERVICES (connectors | skills | llm | auth | mcp-client)     │
│     mcp-client = existing (connects TO external MCP servers)            │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L2: PROCESSING (ingestion | retrieval)                                  │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L1: STORAGE (Qdrant, Memgraph, PostgreSQL clients)                      │
└─────────────────────────────────────┬───────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ L0: CORE (Config, interfaces, base classes, utilities)                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Insight: Bidirectional MCP

Metatron already has `mcp/client.py` (L3) for **consuming** external MCP servers. The new `mcp/server.py` (L6) will **expose** Metatron's capabilities. These are separate concerns:

| Direction | Layer | Purpose | File |
|-----------|-------|---------|------|
| **Client** (inbound) | L3 | Connect Metatron TO external tools | `mcp/client.py` |
| **Server** (outbound) | L6 | Expose Metatron TO external hosts | `mcp/server.py` |

## Component Boundaries

| Component | Layer | Responsibility | Communicates With |
|-----------|-------|----------------|-------------------|
| `mcp/server.py` | L6 | MCP protocol, tool registration, transport handling | Calls L4 Agent, L2 Retrieval |
| `mcp/tools.py` | L6 | Tool definitions (search, get, store, sync) | Calls L2 Retrieval, L1 Storage |
| `mcp/resources.py` | L6 | Resource definitions (documents, workspaces) | Calls L1 Storage |
| `mcp/transport.py` | L6 | stdio, HTTP, SSE transport implementations | MCP SDK |
| `mcp/client.py` | L3 | Connect to external MCP servers (existing) | External MCP servers |
| `mcp/adapter.py` | L3 | Convert MCP tool results → Documents (existing) | L2 Ingestion |

## Data Flow

### MCP Server Request Flow (OpenClaw → Metatron)

```
OpenClaw (MCP Host)
    ↓ stdio/HTTP/SSE
┌─────────────────────────────────────────┐
│ L6: MCP Server                          │
│   transport.py receives JSON-RPC        │
│   server.py routes to tool handler      │
└─────────────────────────────────────────┘
    ↓ tool call (e.g., metatron_search)
┌─────────────────────────────────────────┐
│ L2: Retrieval                           │
│   hybrid_search_and_answer()            │
│   → Qdrant (dense), BM25 (sparse),      │
│     Memgraph (graph)                    │
└─────────────────────────────────────────┘
    ↓ results
┌─────────────────────────────────────────┐
│ L6: MCP Server                          │
│   Format as MCP content blocks          │
│   Return via transport                  │
└─────────────────────────────────────────┘
    ↓ JSON-RPC response
OpenClaw receives answer with sources
```

### MCP Tool Registration Pattern

```python
# src/metatron/mcp/server.py
from mcp.server.fastmcp import FastMCP
from metatron.retrieval.search import hybrid_search_and_answer

mcp = FastMCP("Metatron", stateless_http=True, json_response=True)

@mcp.tool()
async def metatron_search(query: str, workspace_id: str) -> str:
    """Search the knowledge base for relevant documents."""
    result = await hybrid_search_and_answer(query, workspace_id)
    return result

# Mount in existing FastAPI app
# src/metatron/api/app.py
from starlette.routing import Mount

app = FastAPI(
    routes=[
        Mount("/mcp", app=mcp.streamable_http_app()),
    ],
    lifespan=combined_lifespan,
)
```

## Architectural Patterns

### Pattern 1: FastMCP Decorator Pattern

**What:** Use `@mcp.tool()` decorators to expose functions as MCP tools. The SDK handles schema generation from type hints.

**When:** All tool definitions — simple, declarative, type-safe.

**Trade-offs:**
- Pros: Minimal boilerplate, automatic inputSchema generation, Pydantic validation
- Cons: Less control over schema, requires function signature discipline

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Metatron")

@mcp.tool()
async def metatron_search(
    query: str,
    workspace_id: str,
    limit: int = 10,
) -> str:
    """Search the knowledge base.
    
    Args:
        query: Natural language search query
        workspace_id: Target workspace
        limit: Max results (default 10)
    
    Returns:
        Answer with source citations
    """
    return await hybrid_search_and_answer(query, workspace_id, limit)

@mcp.tool()
async def metatron_store(
    content: str,
    title: str,
    workspace_id: str,
) -> str:
    """Store a document in the knowledge base."""
    doc = await ingest_document(content, title, workspace_id)
    return f"Stored: {doc.source_id}"
```

### Pattern 2: Mount to Existing ASGI App

**What:** Mount MCP server alongside FastAPI routes in the same Starlette app.

**When:** When you have an existing API and want MCP on a sub-path.

**Trade-offs:**
- Pros: Single process, shared lifespan, shared dependencies
- Cons: Must coordinate session managers in lifespan

```python
import contextlib
from starlette.applications import Starlette
from starlette.routing import Mount
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Metatron", stateless_http=True, json_response=True)

@mcp.tool()
async def metatron_search(query: str) -> str:
    ...

@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    async with mcp.session_manager.run():
        yield  # Share with existing DB connections, etc.

app = Starlette(
    routes=[
        Mount("/mcp", app=mcp.streamable_http_app()),
        # Existing API routes...
    ],
    lifespan=lifespan,
)
```

### Pattern 3: stdio Transport for Local Tools

**What:** Run MCP server via stdio for local CLI tools (Claude Desktop, OpenClaw local).

**When:** Local development, desktop apps, no HTTP needed.

```python
# src/metatron/mcp/server.py
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

OpenClaw config:
```json
{
  "agents": [{
    "mcp": {
      "servers": [{
        "name": "metatron",
        "command": "python",
        "args": ["-m", "metatron.mcp.server"]
      }]
    }
  }]
}
```

### Pattern 4: Hybrid HTTP/SSE Transport

**What:** Streamable HTTP transport supports both POST (requests) and GET (SSE stream for notifications).

**When:** Production deployments, remote access, streaming responses.

```python
mcp = FastMCP("Metatron", stateless_http=True, json_response=True)

# Configure path (default is /mcp)
mcp.settings.streamable_http_path = "/"

# Mount and run with uvicorn
app = mcp.streamable_http_app()
# Clients connect to: POST /mcp (requests), GET /mcp (SSE stream)
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: MCP Server in Lower Layer

**What people do:** Put MCP server in L3 (domain services) alongside MCP client.

**Why it's wrong:** MCP Server is an **exposure layer** (API-like), not a domain service. It depends on retrieval, agent, storage — all upper layers relative to L3. This would violate the dependency rule (L3 cannot import L4+).

**Do this instead:** MCP Server is L6, same tier as REST API. It calls down to L4 Agent and L2 Retrieval.

### Anti-Pattern 2: Duplicate Business Logic in MCP Tools

**What people do:** Implement search logic directly in MCP tool functions.

**Why it's wrong:** Violates DRY, creates divergence between REST API and MCP behavior.

**Do this instead:** MCP tools delegate to existing functions:
- `metatron_search` → `retrieval.search.hybrid_search_and_answer()`
- `metatron_store` → `ingestion.pipeline.ingest_document()`
- `metatron_sync` → `connectors.registry.sync_connector()`

### Anti-Pattern 3: Stateful MCP Server Without Session Management

**What people do:** Store request state in global variables.

**Why it's wrong:** Multiple concurrent clients will corrupt state. MCP protocol supports sessions for a reason.

**Do this instead:** Use FastMCP's `stateless_http=True` for stateless tools, or pass workspace_id/user_id via tool arguments. For stateful sessions, use the session manager properly.

## Transport Selection

| Transport | Use Case | Security | Performance |
|-----------|----------|----------|-------------|
| **stdio** | Local tools (Claude Desktop, OpenClaw local) | Process isolation | Best (no network) |
| **HTTP+SSE** | Remote access, multi-client, production | TLS, OAuth | Good (connection pooling) |

**Recommendation for OpenClaw integration:**
- Primary: **stdio** — simplest for users, works with local OpenClaw
- Secondary: **HTTP+SSE** — for remote deployments, multi-tenant scenarios

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-1k users | Single process, stdio transport, existing Qdrant/Memgraph |
| 1k-100k users | HTTP transport, load balancer, connection pooling |
| 100k+ users | Separate MCP server process, async workers, Redis for session state |

### Scaling Priorities

1. **First bottleneck:** LLM calls in retrieval pipeline — use caching, async batching
2. **Second bottleneck:** Qdrant/Memgraph queries — add read replicas, connection pooling

## Integration Points

### External Services (OpenClaw)

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| OpenClaw | MCP Host (stdio) | User configures in `openclaw.json` |
| OpenClaw Remote | MCP Host (HTTP+SSE) | Requires TLS, auth |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| MCP Server → L4 Agent | Direct async calls | Router handles intent classification |
| MCP Server → L2 Retrieval | Direct async calls | `hybrid_search_and_answer()` |
| MCP Server → L1 Storage | Via L2/L3 | Never bypass L2 |

## Build Order Implications

Based on dependencies, recommended implementation order:

1. **Phase 1: Core MCP Server**
   - `mcp/server.py` — FastMCP instance, basic tool registration
   - `mcp/tools.py` — Tool definitions (search, get, store, sync)
   - Dependency: L2 Retrieval (existing)

2. **Phase 2: Transport Layer**
   - stdio transport for local tools
   - HTTP/SSE transport for remote access
   - Mount to existing FastAPI app

3. **Phase 3: Resources & Prompts**
   - `mcp/resources.py` — Expose documents, workspaces as resources
   - `mcp/prompts.py` — Predefined prompt templates

4. **Phase 4: Auth & Security**
   - Workspace isolation in tool arguments
   - Optional OAuth for HTTP transport

5. **Phase 5: OpenClaw Integration**
   - Config helper for `openclaw.json`
   - Documentation, installer script

## Sources

- **HIGH Confidence:**
  - Context7: `/modelcontextprotocol/python-sdk` — Official Python SDK docs
  - Context7: `/websites/modelcontextprotocol_io_specification_2025-11-25` — MCP Specification
  - Official MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk

- **MEDIUM Confidence:**
  - WebSearch: "MCP Server Best Practices for 2026" (CData, 2025-12-19)
  - WebSearch: "15 Best Practices for Building MCP Servers in Production" (The New Stack, 2025-09-15)
  - WebSearch: "How to Build a Python MCP Server to Consult a Knowledge Base" (Auth0, 2025-08-29)

- **Verified Patterns:**
  - FastMCP decorator pattern — official SDK examples
  - Starlette/FastAPI mounting — official SDK examples
  - stdio and HTTP transports — MCP specification

---
*Architecture research for: MCP Server Integration with Metatron*
*Researched: 2026-02-22*
