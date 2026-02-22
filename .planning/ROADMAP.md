# Roadmap: Metatron OpenClaw Integration

## Overview

Transform Metatron into an MCP Server that OpenClaw users can connect to for structured, searchable long-term memory. The journey delivers a working MCP server, production deployment stack, easy one-line installer, and seamless OpenClaw integration docs.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: MCP Server Foundation** - Core tools + both transports + metatron_sync
- [ ] **Phase 2: Deployment & Sync** - Docker Compose stack + background sync + temporal versioning
- [ ] **Phase 3: Installer & Distribution** - One-line curl installer with security best practices
- [ ] **Phase 4: OpenClaw Integration** - Config templates + quickstart + troubleshooting docs

## Phase Details

### Phase 1: MCP Server Foundation
**Goal**: Working MCP server with all tools exposed, both transports working, ready for external host integration.
**Depends on**: Nothing (first phase)
**Requirements**: MCP-01, MCP-02, MCP-03, MCP-04, MCP-05, MCP-06, TRNS-01, TRNS-02, TRNS-03, SYNC-01
**Success Criteria** (what must be TRUE):
  1. User can search knowledge base via `metatron_search` and receive relevant, paginated results
  2. User can retrieve specific documents via `metatron_get` using doc_label/Jira key/Confluence ID
  3. User can store new memories via `metatron_store` with content and metadata
  4. User can check system health via `metatron_status` (doc count, last sync, embedding model)
  5. User can trigger sync via `metatron_sync` for configured sources
  6. MCP server runs via stdio for local development AND StreamableHTTP for production
   7. MCP server mounts to existing FastAPI app with shared lifespan
**Plans:** 3 plans

Plans:
- [ ] 01-01-PLAN.md — MCP Server Core Tools (search, get, store, status)
- [ ] 01-02-PLAN.md — Transport & FastAPI Integration
- [ ] 01-03-PLAN.md — Gap Closure: HTTP Transport Fix

### Phase 2: Deployment & Sync
**Goal**: Complete deployable Docker Compose stack with bi-directional sync and temporal versioning.
**Depends on**: Phase 1
**Requirements**: DEPL-01, DEPL-02, DEPL-03, SYNC-02, SYNC-03
**Success Criteria** (what must be TRUE):
  1. User can start all services with single `docker-compose up` command
  2. All services wait for healthy dependencies (no startup race conditions)
  3. Documents auto-sync from configured sources (Confluence, Jira, Notion)
  4. Document history is tracked with temporal versioning (changes over time visible)
**Plans**: 2 plans

Plans:
- [ ] 02-01-PLAN.md — Docker Compose Stack (Metatron + PostgreSQL + Qdrant + Memgraph with health checks)
- [ ] 02-02-PLAN.md — Auto-Sync + Temporal Versioning (Background sync manager + document versions)

### Phase 3: Installer & Distribution
**Goal**: Easy installation experience with one-line command and security best practices.
**Depends on**: Phase 2
**Requirements**: INST-01, INST-02, INST-03
**Success Criteria** (what must be TRUE):
  1. User can install with `curl https://app.mtrnix.com/install.sh | bash`
  2. Installer checks and reports missing dependencies (Python 3.12+, Docker optional)
  3. Installer is served over HTTPS with documented checksum verification
**Plans**: 2 plans

Plans:
- [ ] 03-01-PLAN.md — Shell Installer with Dependency Checking (Python 3.12+, Docker detection, repo clone, docker-compose setup)
- [ ] 03-02-PLAN.md — Distribution Setup & Release Automation (HTTPS hosting, GitHub Actions releases, checksum verification)

### Phase 4: OpenClaw Integration
**Goal**: OpenClaw users can connect Metatron as MCP server and get productive quickly.
**Depends on**: Phase 3
**Requirements**: OPEN-01, OPEN-02, OPEN-03
**Success Criteria** (what must be TRUE):
  1. OpenClaw user can copy-paste config template to connect Metatron as MCP server
  2. New user can follow quickstart guide to get Metatron working with OpenClaw in under 10 minutes
  3. User can troubleshoot common issues using troubleshooting guide
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. MCP Server Foundation | 3/3 | ✓ Complete | 2026-02-22 |
| 2. Deployment & Sync | 3/3 | ✓ Complete | 2026-02-22 |
| 3. Installer & Distribution | 0/2 | Planning Complete | - |
| 4. OpenClaw Integration | 0/TBD | Pending Phase 3 | - |

---
*Roadmap created: 2026-02-22*
*Depth: Quick (4 phases)*
*Coverage: 21/21 requirements mapped*
