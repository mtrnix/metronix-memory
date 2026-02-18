# CLAUDE.md — Project Context for Claude Code

## What is this project?
MTRNIX (Metatron Core) is an open-source enterprise knowledge management system.
It ingests documents from Confluence, Jira, Notion, and other sources, builds a knowledge graph,
and answers questions via Telegram/Discord/Slack bots using hybrid RAG (dense vectors + BM25 + graph enrichment).

## Tech Stack
- **Language:** Python 3.12+
- **Vector DB:** Qdrant (hybrid dense + sparse/BM25)
- **Graph DB:** Memgraph (knowledge graph, entity relationships)
- **Relational DB:** PostgreSQL (auth, workspaces, sync metadata)
- **LLM Providers:** Ollama (local), DeepSeek, OpenRouter (cloud fallback)
- **Embeddings:** sentence-transformers via Ollama (nomic-embed-text, 768 dims)
- **Bot Framework:** aiogram 3.x (Telegram), discord.py 2.x (Discord), slack-bolt (Slack)
- **Web Framework:** FastAPI
- **Testing:** pytest

## Project Structure
```
src/metatron/
├── core/           # Models, interfaces, config, exceptions (ZERO deps)
├── storage/        # Qdrant, Memgraph, PostgreSQL clients
├── observability/  # Metrics, health, tracing
├── ingestion/      # Chunking, BM25, dedup, date/text processors
├── retrieval/      # Search pipeline, query expansion, prompts, scoring
├── connectors/     # Confluence, Jira, Notion
├── llm/            # Multi-provider LLM (Ollama, DeepSeek, OpenRouter)
├── mcp/            # MCP Client — universal tool/connector via Model Context Protocol
├── auth/           # JWT, RBAC, user mapping
├── agent/          # Router, sessions, executor, tools, commands
├── channels/       # Telegram, Discord, Slack bots
├── skills/         # Skill engine (stub)
├── workspaces/     # Multi-tenant workspace management
└── api/            # FastAPI routes (REST + SSE streaming)
tests/unit/         # pytest — mirrors src/ structure (751 tests)
docs/               # TODO.md, architecture decisions
```

## Architecture Layers (dependency direction: top depends on bottom only)

Layer 0: `core/` — models, interfaces, config, exceptions, logging (ZERO dependencies)
Layer 1: `storage/`, `observability/` — data access (depends on core only)
Layer 2: `ingestion/`, `retrieval/` — document processing, search (depends on core + storage)
Layer 3: `connectors/`, `skills/`, `llm/`, `auth/`, `mcp/` — integrations (depends on core + storage + layer 2)
Layer 4: `agent/` — orchestration (depends on core + retrieval + skills + llm + mcp)
Layer 5: `channels/` — messengers (depends on core + agent)
Layer 6: `api/` — HTTP endpoints (depends on everything)

NEVER import from a higher layer. If you need something from a higher layer, add an interface to `core/` or pass it as a parameter.

## Search Pipeline (hybrid_search_and_answer)
The main entry point is `retrieval/search.py::hybrid_search_and_answer()`. Flow:
1. `rq = intent_query` (current message for lang detection + person regex)
2. `lang = detect_response_language(rq)` — 30% Cyrillic threshold
3. `eq = expand_query(rq)` — LLM adds BM25 keywords
4. `sq = translate_to_english(eq)` — if Cyrillic
5. **Jira key injection**: `_inject_jira_key_results(rq)` — exact doc_label lookup for PROJ-123 patterns
6. **Person/activity injection** (`elif` — person XOR activity):
   - `if person` → `search_by_assignee(resolve_person_name(person))` (supports Russian case endings)
   - `elif activity` → `search_by_status("In Progress"/"В работе"/...)`
7. `raw = search_with_date_filter(sq, date_query=rq)` — ±7 day widening
8. `raw = merge(jira_key_results, injected, raw)` — Jira keys highest priority
9. `base = diversify_results(raw)` — min 2 per source type
10. `frags = collect_frags(base)` — `[JIRA]`/`[CONFLUENCE]`/`[NOTION]` labels
11. Graph enrichment via Memgraph (with retry on stale connections)
12. LLM answer (prompt has `{response_language}`)
13. `return append_sources(answer, base)` — emoji citations

## Code Rules

- Python 3.12. No 3.13+ features.
- async/await for all I/O. No sync DB calls, no sync HTTP, no time.sleep().
- Type hints on every function signature. No `Any` unless truly unavoidable.
- Pydantic v2 style: `model_config = ConfigDict(...)`, not `class Config`.
- structlog for all logging. No print(). No logging module directly.
- Every public function: docstring + type hints + structlog call for important operations.
- Files < 200 lines. If longer, split into focused modules.
- Imports: absolute only. `from metatron.core.models import Chunk` — never relative.
- Exceptions: no bare `except:`. Always catch specific types. Use exceptions from `core/exceptions.py`.
- No global mutable state. No singletons. Dependency injection via constructor or function params.
- Tests: pytest + pytest-asyncio. Test file mirrors source: `src/metatron/retrieval/scoring.py` → `tests/unit/test_scoring.py`

## Naming Conventions

- Files: snake_case.py
- Classes: PascalCase
- Functions/methods: snake_case
- Constants: UPPER_SNAKE_CASE
- Private methods: _prefixed
- Interfaces: NameInterface (ConnectorInterface, not IConnector)
- Implementations: DescriptiveName (ConfluenceConnector, OllamaProvider)

## Commit Messages

Format: `<scope>: <description>`
Scopes: core, storage, ingestion, retrieval, connectors, mcp, skills, agent, channels, api, auth, observability, infra, docs, tests
Examples:
- `connectors: implement Confluence fetch with pagination`
- `retrieval: add graph enrichment step to hybrid search`
- `infra: fix docker-compose healthcheck for memgraph`

## Bot Commands (Telegram / Discord / Slack)

- `/search <query>` — Explicit knowledge base search
- `/sync confluence|jira|notion` — Incremental sync (only changes)
- `/sync confluence|jira|notion full` — Full re-sync from scratch
- `/mcp list` — List configured MCP servers
- `/mcp add <name> <command> [args...]` — Register MCP server
- `/mcp remove <name>` — Remove MCP server
- `/mcp sync <name> [full]` — Sync one MCP server
- `/mcp sync-all [full]` — Sync all MCP servers
- `/mcp tools <name>` — List tools from MCP server
- `/rebuild-aliases` — Rebuild person name registry from stored data
- `/status` — Show workspace status (doc counts, LLM provider, connectors)
- `/clear` — Clear conversation history
- `/help` — List commands

Natural language also works — just type a question. Action requests ("create a Jira ticket...") trigger the ACTION intent and use MCP tool execution.

## Intent Classification

The router (`agent/router.py`) classifies every message into one of 5 intents:
- **COMMAND** — starts with `/` or `!`
- **GREETING** — "hello", "привет", etc.
- **SMALLTALK** — "how are you", "thanks", etc.
- **ACTION** — "create", "send", "update" keywords → MCP action planning + execution
- **SEARCH** — everything else → hybrid search pipeline

## API Endpoints

```
GET  /health                              — Health check (Qdrant, Memgraph, Ollama probes)
GET  /ready                               — Readiness probe
GET  /metrics                             — Prometheus-format metrics
POST /metrics/reset                       — Reset metrics counters

POST /api/v1/chat                         — Chat (sync response)
POST /api/v1/chat/stream                  — Chat (SSE streaming)
POST /api/v1/upload                       — File upload (PDF, DOCX, TXT, MD)

GET  /api/v1/workspaces                   — List workspaces
POST /api/v1/workspaces                   — Create workspace
GET  /api/v1/workspaces/{id}              — Get workspace
DELETE /api/v1/workspaces/{id}            — Delete workspace
POST /api/v1/workspaces/{id}/activate     — Activate workspace
GET  /api/v1/workspaces/{id}/stats        — Workspace stats

GET  /api/v1/connections                  — List connections
POST /api/v1/connections                  — Create connection
POST /api/v1/connections/{id}/sync        — Sync connection
POST /api/v1/connections/sync/{type}      — Sync by connector type
DELETE /api/v1/connections/{id}           — Delete connection

GET  /api/v1/admin/cleanup/preview        — Preview cleanup
DELETE /api/v1/admin/cleanup/workspace/{id} — Cleanup workspace data
DELETE /api/v1/admin/cleanup/all          — Cleanup all data
GET  /api/v1/admin/status                 — Admin status

POST /api/v1/benchmarker/query/trace      — Query trace with 7-step breakdown
```

## Running

```bash
# Tests (751 tests)
.venv/bin/pytest tests/ -v --tb=short

# Unified launcher (API + Telegram + Discord + Slack bots)
.venv/bin/python -m metatron.app

# API server only
.venv/bin/python -m metatron.api.app
```

## Key Files to Read First

- `core/interfaces.py` — all contracts
- `core/models.py` — all data structures
- `core/config.py` — all settings (env vars)
- `retrieval/search.py` — main search pipeline (hybrid RAG + Jira key injection)
- `retrieval/prompts.py` — LLM system prompts
- `agent/router.py` — intent classification + dispatch (5 intents: SEARCH, GREETING, SMALLTALK, COMMAND, ACTION)
- `agent/sessions.py` — conversation history + follow-up detection
- `mcp/client.py` — MCP Client (SSE transport, tool listing, tool execution)
- `mcp/adapter.py` — GenericMCPAdapter (two-phase: read tools for sync, action tools for execution)

## When Creating a New Connector

**Option A: Native connector** (for major integrations like Confluence, Jira, Notion):
1. Create `src/metatron/connectors/<name>.py`
2. Implement ConnectorInterface (see `core/interfaces.py`)
3. Register in `connectors/registry.py`
4. Add credentials schema to docstring

**Option B: MCP server** (for quick integrations — any tool that speaks MCP):
1. `/mcp add <name> <command> [args...]` — registers an external MCP server
2. `/mcp sync <name>` — syncs documents using the server's read tools
3. Action tools are available automatically for LLM-driven execution

## When Modifying Database Schema

1. Create new migration: `alembic revision -m "description"`
2. Write upgrade() and downgrade()
3. Test: `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head`
4. Update `core/models.py` if new data structures needed
