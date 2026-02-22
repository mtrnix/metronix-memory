# Phase 1: MCP Server Foundation - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Build an MCP Server that exposes Metatron's knowledge capabilities to external hosts like OpenClaw. Users (AI agents) will CALL this server to search, retrieve, store, and sync documents. The server must support both stdio transport (local development) and StreamableHTTP transport (production).

</domain>

<decisions>
## Implementation Decisions

### Tool Responses

- **Search results include graph context**: Each result contains chunk text (~700 chars), source type, doc_label, score, timestamp, PLUS related entities and linked documents from knowledge graph
- **Structured error format**: Errors return JSON with `error.code` (machine-readable), `error.message` (human-readable), `error.hint` (suggested next action)
- **Cursor-based pagination**: Use cursor tokens for stable pagination instead of offset-based (handles dynamic data changes better)
- **Claude's Discretion**: Store response format (metadata vs minimal confirm)

### Transport Behavior

- **stdio workspace context**: Read from `~/.metatron/config.json` at startup
- **HTTP authentication**: API key via `Authorization: Bearer <key>` header
- **Claude's Discretion**: 
  - HTTP workspace context passing method
  - Whether stdio and HTTP expose identical capabilities or differ
  - Transport capability parity decisions

### Sync Behavior

- **Claude's Discretion**:
  - Sync triggering (manual only vs scheduled vs hybrid)
  - Sync feedback (background with status vs blocking vs progress updates)
  - Sync failure handling for individual sources
  - Incremental vs full sync support

### Error Handling

- **Claude's Discretion**:
  - Retry behavior for transient failures
  - Graceful degradation when services (Qdrant/Memgraph/Postgres) are down
  - Timeout handling for long-running operations

### Claude's Discretion Summary

The following areas are left to Claude's judgment during planning/implementation:
- Store response format details
- HTTP workspace context passing method (header vs URL path vs token-embedded)
- Transport capability parity (identical vs HTTP-richer vs stdio-richer)
- All sync behavior decisions (triggering, feedback, failure handling, incremental support)
- All error handling decisions (retry, degradation, timeouts)

</decisions>

<specifics>
## Specific Ideas

- "Config file: read from ~/.metatron/config.json" — explicit user preference for stdio config location
- API key authentication for HTTP — simpler than JWT for self-hosted deployments
- Graph-enriched search results — leverage existing Memgraph knowledge graph for better context

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-mcp-server-foundation*
*Context gathered: 2026-02-22*
