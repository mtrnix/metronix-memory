# Project Research Summary

**Project:** Metatron MCP Server (OpenClaw Integration)
**Domain:** MCP Server implementation for RAG/knowledge backend integration
**Researched:** 2026-02-22
**Confidence:** HIGH

## Executive Summary

This project adds an **MCP Server** to Metatron, enabling external MCP hosts (like OpenClaw) to search and store in Metatron's knowledge base. The Model Context Protocol (MCP) is the emerging standard for connecting AI assistants to external tools and data sources, with FastMCP 3.x being the de facto implementation framework.

**Recommended approach:** Build an L6 MCP Server using FastMCP 3.x with StreamableHTTP transport for production and stdio for local development. The server will expose 4 core tools (`metatron_search`, `metatron_get`, `metatron_store`, `metatron_status`) that delegate to Metatron's existing L2 Retrieval and L3 Ingestion layers. This preserves architectural boundaries while providing external access.

**Key risks:** STDIO transport logging corruption (print() breaks JSON-RPC), token passthrough anti-patterns, and curl|bash installer security. Mitigation: configure all logging to stderr from day one, obtain server-scoped tokens rather than passing through user tokens, and serve installer over HTTPS with checksum verification.

## Key Findings

### Recommended Stack

The MCP ecosystem has converged on FastMCP as the standard framework. It's built on the official `mcp` Python SDK but provides a decorator-based API that eliminates boilerplate and auto-generates tool schemas from type hints.

**Core technologies:**
- **FastMCP 3.0.1+** — MCP Server framework — 1M+ daily downloads, decorator-based API, built on official SDK
- **Uvicorn 0.34+** — ASGI server — Required for StreamableHTTP transport in production
- **Pydantic 2.x** — Schema validation — Auto-generates JSON schemas from type hints (already in Metatron)

**Transport selection:**
- **StreamableHTTP** — Production/remote access — Default for MCP spec since Nov 2024, supports horizontal scaling with `stateless_http=True`
- **stdio** — Local development only — For Claude Desktop / OpenClaw local integration

**Critical version notes:**
- SSE transport is DEPRECATED — do not use
- FastMCP v2 is obsolete — v3 (Feb 2026) added OAuth, OpenTelemetry, better ASGI integration
- `stateless_http=True` is mandatory for load-balanced deployments

### Expected Features

**Must have (table stakes):**
- `metatron_search(query, workspace_id, limit)` — Semantic search with hybrid RAG (dense + BM25)
- `metatron_get(doc_label)` — Direct lookup by document label (Jira key, Confluence page ID)
- `metatron_store(content, metadata, workspace_id)` — Store memories/documents
- `metatron_status()` — System health: doc count, last sync, embedding model status
- Proper tool descriptions — LLM must select correct tool without hints
- Pagination — Default limit 10-50, return `has_more`, `next_offset`, `total`

**Should have (competitive):**
- Hybrid search (dense + BM25) — Handles technical terms, proper nouns better than vector-only
- Knowledge graph enrichment — Entity relationships via Memgraph
- Workspace isolation — Multi-tenant support
- Temporal filtering — Date-aware queries ("what did we decide last week?")

**Defer (v2+):**
- Streaming responses — SSE for long searches; requires more infrastructure
- Person/activity queries — Alias registry + status filtering; language-specific patterns
- Query expansion — LLM-based synonym injection; latency tradeoff
- Memory plugin integration — Deeper OpenClaw integration via plugin slot

**Anti-features to avoid:**
- Thin REST API wrapper — Forces agents to orchestrate multiple calls
- Complex nested arguments — Agents hallucinate keys; use `Literal` types instead
- Unbounded result sets — Context window overflow
- Raw API responses — Curate for agent consumption
- Too many tools (>15) — Discovery cost, confusion

### Architecture Approach

MCP Server integrates as a **new L6 component** that exposes Metatron's capabilities externally. This respects existing layer boundaries: MCP Server calls down to L4 Agent and L2 Retrieval, never bypassing to L1 Storage directly.

**Bidirectional MCP insight:**
- MCP Client (L3, existing) — Connects Metatron TO external MCP servers for data ingestion
- MCP Server (L6, new) — Exposes Metatron TO external hosts like OpenClaw

**Major components:**
1. `mcp/server.py` — FastMCP instance, tool registration, transport handling
2. `mcp/tools.py` — Tool definitions (search, get, store, status) that delegate to existing functions
3. `mcp/transport.py` — stdio and StreamableHTTP transport implementations
4. Optional: `mcp/resources.py` — Expose documents/workspaces as MCP resources

**Key architectural pattern:** MCP tools must delegate to existing functions, never duplicate business logic. `metatron_search` → `retrieval.search.hybrid_search_and_answer()`, not new implementation.

### Critical Pitfalls

1. **STDIO logging corruption** — Any `print()` or stdout write corrupts JSON-RPC. Configure all logging to stderr BEFORE any server code runs. Add CI check for `print(` in server code.

2. **Token passthrough anti-pattern** — Server accepts raw user tokens and forwards them downstream. Breaks audit trails, bypasses rate limits. Server MUST obtain its own tokens for downstream services.

3. **Tool selection confusion** — Poor naming causes LLM to call wrong tool. Use distinct names (`metatron_search_docs`, not just `search`), write descriptions that explain WHEN to use, keep tool count under 15.

4. **curl | bash blind execution** — Installer served without HTTPS or checksum. MITM = RCE. Serve over HTTPS ONLY, provide checksum/signature option, document review-before-run pattern.

5. **Multi-service startup race conditions** — Docker Compose starts Metatron before Qdrant/Memgraph ready. Use `healthcheck` + `depends_on: condition: service_healthy`, implement retry with backoff.

6. **Response token bloat** — Tool responses dump entire documents. Paginate all list operations (default 10-50), truncate text with "..." and offer `get_full` tool.

7. **SSE transport deprecation** — Old tutorials show SSE, but it's deprecated. Use Streamable HTTP for remote, stdio for local. Never use SSE for new projects.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: MCP Server Core
**Rationale:** Foundation that all other features depend on. Must get transport, tool definitions, and auth patterns right from the start.
**Delivers:** Working MCP server with 4 core tools, stdio and HTTP transports
**Addresses:** Table stakes features (search, get, store, status)
**Avoids:** STDIO logging corruption, token passthrough, tool naming confusion, response bloat, SSE deprecation
**Stack:** FastMCP 3.x, Uvicorn, Pydantic

### Phase 2: Transport & Integration
**Rationale:** Production-ready deployment with both transports working, mounted to existing FastAPI app.
**Delivers:** StreamableHTTP transport, shared lifespan with existing app, OpenClaw config helper
**Uses:** FastMCP's `streamable_http_app()`, Starlette mounting patterns
**Implements:** ASGI integration from ARCHITECTURE.md Pattern 2

### Phase 3: One-Line Installer
**Rationale:** User experience is critical for adoption. curl|bash installer with security best practices.
**Delivers:** HTTPS-served installer script, checksum verification, dependency checks
**Avoids:** curl|bash blind execution pitfall
**Stack:** Shell script, CDN hosting

### Phase 4: Full Stack Docker Compose
**Rationale:** Complete deployment including Qdrant, Memgraph, PostgreSQL with proper orchestration.
**Delivers:** docker-compose.yml with healthchecks, dependency ordering, /ready endpoint
**Avoids:** Multi-service startup race conditions
**Stack:** Docker Compose, healthchecks, service_healthy conditions

### Phase 5: OpenClaw Integration Package
**Rationale:** Documentation and tooling for OpenClaw users to configure Metatron as MCP server.
**Delivers:** Config templates, quickstart guide, troubleshooting docs
**Addresses:** User onboarding for target integration

### Phase Ordering Rationale

- Phase 1 first because all other phases depend on a working MCP server
- Phase 2 before Phase 3 because production transport is prerequisite for installer
- Phase 3 before Phase 4 because installer should work with single service before multi-service
- Phase 4 before Phase 5 because full stack is prerequisite for OpenClaw integration docs
- This order ensures each phase validates the previous before moving forward

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2:** OpenClaw's MCP client implementation details — need to verify config format, transport support
- **Phase 4:** Docker Compose networking patterns for MCP — standard patterns exist but may need adjustment for MCP-specific ports

Phases with standard patterns (skip research-phase):
- **Phase 1:** Well-documented FastMCP patterns, official SDK examples available
- **Phase 3:** Standard curl|bash installer patterns, well-known security best practices
- **Phase 5:** Documentation-focused, no novel technical challenges

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Official MCP Python SDK docs, FastMCP is de facto standard (1M+ downloads/day), Context7 sources |
| Features | HIGH | Multiple competitor implementations analyzed, Phil Schmid best practices, OWASP security guide |
| Architecture | HIGH | Context7 official docs, official Python SDK, fits naturally with Metatron's existing layers |
| Pitfalls | HIGH | NearForm tips/tricks guide, Hailey Quach security guide, Trend Trend MCP security, official SDK docs |

**Overall confidence:** HIGH

### Gaps to Address

- **OpenClaw config format:** Need to verify exact configuration format OpenClaw expects for MCP servers. Documented in Phase 2 planning.
- **Production auth strategy:** OAuth patterns mentioned in FastMCP 3.x but not deeply researched. May need `/gsd-research-phase` if complex auth required.
- **Streaming vs JSON responses:** FastMCP supports both; decision on streaming for long searches deferred to implementation. Test with real data.

## Sources

### Primary (HIGH confidence)
- Context7: `/modelcontextprotocol/python-sdk` — Official MCP Python SDK v1.26.0, FastMCP patterns, transport options
- Context7: `/websites/modelcontextprotocol_io_specification_2025-11-25` — MCP Specification, tool definitions
- PyPI: `mcp` 1.26.0, `fastmcp` 3.0.1 — Package versions and download statistics
- https://gofastmcp.com/v2/deployment/http — Production HTTP deployment guide

### Secondary (MEDIUM confidence)
- Phil Schmid: "MCP Best Practices" — Tool design guidelines
- OWASP: "Practical Guide for Secure MCP Server Development" — Security considerations
- NearForm: "Implementing MCP: Tips, Tricks and Pitfalls" — Pitfall identification
- Hailey Quach: "MCP Security Survival Guide" — Token passthrough, auth patterns
- Docker Docs: "Control startup order in Compose" — Healthcheck patterns

### Tertiary (LOW confidence)
- Various: curl | bash security discussions — Community consensus, no single authoritative source

---
*Research completed: 2026-02-22*
*Ready for roadmap: yes*
