# Requirements: Metatron OpenClaw Integration

**Defined:** 2026-02-22
**Core Value:** Replace OpenClaw's amnesia with structured, searchable long-term memory via MCP Server integration.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### MCP Tools

- [ ] **MCP-01**: User can search knowledge base with `metatron_search` tool (hybrid RAG: dense + BM25)
- [ ] **MCP-02**: User can retrieve specific document with `metatron_get` tool (by doc_label/Jira key/Confluence ID)
- [ ] **MCP-03**: User can store memories with `metatron_store` tool (content + metadata)
- [ ] **MCP-04**: User can check system health with `metatron_status` tool (doc count, last sync, embedding model)
- [ ] **MCP-05**: MCP tools have proper descriptions for LLM tool selection
- [ ] **MCP-06**: Search results are paginated (default limit, has_more, next_offset)

### Transport

- [ ] **TRNS-01**: MCP server supports stdio transport (for local development, Claude Desktop)
- [ ] **TRNS-02**: MCP server supports StreamableHTTP transport (for production, OpenClaw remote)
- [ ] **TRNS-03**: MCP server mounts to existing FastAPI app with shared lifespan

### Installer

- [ ] **INST-01**: User can install with one-line command (`curl ... | bash`)
- [ ] **INST-02**: Installer is served over HTTPS with checksum verification
- [ ] **INST-03**: Installer checks dependencies (Python 3.12+, Docker optional)

### Deployment

- [ ] **DEPL-01**: Docker Compose includes all services (Metatron, Qdrant, Memgraph, PostgreSQL)
- [ ] **DEPL-02**: Docker Compose has healthchecks with proper dependency ordering
- [ ] **DEPL-03**: Services wait for healthy dependencies before starting

### OpenClaw Integration

- [ ] **OPEN-01**: Config template provided for OpenClaw `mcp.servers[]` setup
- [ ] **OPEN-02**: Quickstart documentation for OpenClaw users
- [ ] **OPEN-03**: Troubleshooting guide for common issues

### Bi-directional Sync

- [ ] **SYNC-01**: User can sync documents from configured sources via `metatron_sync` tool
- [ ] **SYNC-02**: Documents auto-update from sources (Confluence, Jira, Notion)
- [ ] **SYNC-03**: Temporal versioning - documents track changes over time

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Features

- **MCP-07**: Streaming responses for long searches (SSE)
- **MCP-08**: Person/activity queries with alias registry
- **MCP-09**: Query expansion with LLM-based synonyms
- **MCP-10**: Knowledge graph exposed as MCP resources

### Deep Integration

- **OPEN-04**: Memory plugin for OpenClaw (`plugins.slots.memory = "metatron"`)
- **OPEN-05**: OAuth authentication for multi-user scenarios

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| SSE transport | Deprecated in MCP spec, use StreamableHTTP |
| Thin REST wrapper | Forces agents to orchestrate multiple calls |
| Raw API responses | Curate for agent consumption |
| Too many tools (>15) | Discovery cost, confusion |
| OpenClaw core modifications | Must work with stock OpenClaw |
| Cloud-hosted Metatron | Self-hosted only for v1 |
| Mobile apps | OpenClaw handles messaging layer |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| MCP-01 | Phase 1 | Pending |
| MCP-02 | Phase 1 | Pending |
| MCP-03 | Phase 1 | Pending |
| MCP-04 | Phase 1 | Pending |
| MCP-05 | Phase 1 | Pending |
| MCP-06 | Phase 1 | Pending |
| TRNS-01 | Phase 1 | Pending |
| TRNS-02 | Phase 1 | Pending |
| TRNS-03 | Phase 1 | Pending |
| INST-01 | Phase 3 | Pending |
| INST-02 | Phase 3 | Pending |
| INST-03 | Phase 3 | Pending |
| DEPL-01 | Phase 2 | Pending |
| DEPL-02 | Phase 2 | Pending |
| DEPL-03 | Phase 2 | Pending |
| OPEN-01 | Phase 4 | Pending |
| OPEN-02 | Phase 4 | Pending |
| OPEN-03 | Phase 4 | Pending |
| SYNC-01 | Phase 1 | Pending |
| SYNC-02 | Phase 2 | Pending |
| SYNC-03 | Phase 2 | Pending |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 21
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-22*
*Last updated: 2026-02-22 after initial definition*
