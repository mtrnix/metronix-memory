# Metatron — Development Process Guide

## Step 0: Right Now (after scaffold is generated)

### 1. Review what Opus generated

Don't blindly trust. Check:
- Does `pyproject.toml` have correct dependencies? Are versions pinned?
- Does `docker-compose.yml` start? Run `docker compose up -d` and verify all 5 services are healthy.
- Do imports work? Run `pip install -e ".[dev]"` then `python -c "from metatron.core.models import Chunk; print('OK')"`
- Do tests pass? Run `pytest tests/unit/` — the implemented modules (chunking, dedup, scoring, rrf, auth) should have passing tests.
- Are migrations valid? Run `alembic upgrade head` against a test PostgreSQL.

Fix anything broken before moving on. This is your foundation — bugs here multiply later.

### 2. Create CLAUDE.md in project root

This is the file Claude Code reads automatically when entering the project. It's your "coding constitution" — rules that every LLM session must follow.

```markdown
# CLAUDE.md — Project Rules for LLM Assistants

## Project

Metatron Core — AI knowledge agent for teams. Python 3.12, FastAPI, async everywhere.

## Architecture layers (dependency direction: top depends on bottom only)

Layer 0: core/ — models, interfaces, config, exceptions, logging (ZERO dependencies)
Layer 1: storage/, observability/ — data access (depends on core only)
Layer 2: ingestion/, retrieval/ — document processing, search (depends on core + storage)
Layer 3: connectors/, skills/, llm/, auth/ — integrations (depends on core + storage + layer 2)
Layer 4: agent/ — orchestration (depends on core + retrieval + skills + llm)
Layer 5: channels/ — messengers (depends on core + agent)
Layer 6: api/ — HTTP endpoints (depends on everything)

NEVER import from a higher layer. If you need something from a higher layer, you're doing it wrong — add an interface to core/ or pass it as a parameter.

## Code rules

- Python 3.12. No 3.13+ features.
- async/await for all I/O. No sync DB calls, no sync HTTP, no time.sleep().
- Type hints on every function signature. No `Any` unless truly unavoidable.
- Pydantic v2 style: `model_config = ConfigDict(...)`, not `class Config`.
- structlog for all logging. No print(). No logging module directly.
- Every public function: docstring + type hints + structlog call for important operations.
- Files < 200 lines. If longer, split into focused modules.
- Imports: absolute only. `from metatron.core.models import Chunk` — never relative.
- Exceptions: no bare `except:`. Always catch specific types. Use exceptions from core/exceptions.py.
- No global mutable state. No singletons. Dependency injection via constructor or function params.
- Tests: pytest + pytest-asyncio. Test file mirrors source: `src/metatron/retrieval/scoring.py` → `tests/unit/test_scoring.py`

## Naming conventions

- Files: snake_case.py
- Classes: PascalCase
- Functions/methods: snake_case
- Constants: UPPER_SNAKE_CASE
- Private methods: _prefixed
- Interfaces: NameInterface (ConnectorInterface, not IConnector)
- Implementations: DescriptiveName (ConfluenceConnector, OllamaProvider)

## Commit messages

Format: `<scope>: <description>`
Scopes: core, storage, ingestion, retrieval, connectors, skills, agent, channels, api, auth, observability, infra, docs, tests
Examples:
- `connectors: implement Confluence fetch with pagination`
- `retrieval: add graph enrichment step to hybrid search`
- `infra: fix docker-compose healthcheck for memgraph`
- `docs: add connector development guide`

## When creating a new connector

1. Create `src/metatron/connectors/<name>.py`
2. Implement ConnectorInterface (see core/interfaces.py)
3. Register in `connectors/registry.py`
4. Add credentials schema to docstring
5. Write skill .md if connector has action capabilities
6. Add to docs/CONNECTORS.md

## When creating a new channel

1. Create `src/metatron/channels/<name>.py`
2. Implement ChannelInterface (see core/interfaces.py)
3. Add to channel registry in channels/__init__.py

## When modifying database schema

1. Create new migration: `alembic revision -m "description"`
2. Write upgrade() and downgrade()
3. Test: `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head`
4. Update core/models.py if new data structures needed

## Key files to understand before working

- core/interfaces.py — all contracts
- core/models.py — all data structures
- core/config.py — all settings
- core/exceptions.py — error hierarchy
```

### 3. Create .cursorrules (for Dev 2 if using Cursor)

Same content as CLAUDE.md but in Cursor format. Copy CLAUDE.md to `.cursorrules` — Cursor reads it automatically.

---

## Developer Split

### Dev 1 (Konstantin) — Agent & Interface

```
Owns:
  src/metatron/core/          — shared contracts (both devs discuss changes)
  src/metatron/agent/         — router, commands, sessions, tools, executor
  src/metatron/channels/      — Telegram, Slack
  src/metatron/skills/        — engine + builtin .md files
  src/metatron/auth/          — JWT, RBAC, user mapping
  src/metatron/api/           — all FastAPI routes
  src/metatron/observability/ — tracer (already implemented), health, metrics
  docker-compose.yml, Dockerfile, Makefile
  docs/

Builds the path: message arrives → agent routes → skills selected →
LLM decides → tools executed → answer sent back via channel.
```

### Dev 2 — Data & Search

```
Owns:
  src/metatron/storage/       — Qdrant, Memgraph, PostgreSQL stores, file_store
  src/metatron/ingestion/     — pipeline, chunking, dedup, processors
  src/metatron/retrieval/     — hybrid search, graph enrichment, scoring, context, fallback
  src/metatron/connectors/    — all native connectors
  src/metatron/llm/           — Ollama, OpenAI-compatible providers
  migrations/

Builds the path: connector fetches docs → ingestion pipeline → Qdrant/Memgraph →
retrieval engine finds results → scoring ranks them → context assembled.
```

### Shared boundary: core/interfaces.py

Both developers depend on this file. Rules:
- Changes to interfaces require discussion (Telegram/Slack message, 5 minutes).
- Never change an interface signature without notifying the other dev.
- If you need a new method on an interface — add it, don't modify existing ones.

### How they connect

Dev 1's agent calls `retriever.search(query, workspace_id)` — this is Dev 2's code.
Dev 2's retriever returns `list[ScoredChunk]` — Dev 1 formats it for the user.

The contract is in `core/interfaces.py: RetrieverInterface`. As long as both follow the interface, they never block each other.

---

## Sprint-by-Sprint Process

### Each sprint (1 week)

**Monday:** 15-min sync. Each dev says: what I'll do this week, what I need from the other.

**Daily:** async update in team chat. Format:
```
Done: connectors: Confluence fetch with pagination working
Doing: connectors: Jira connector
Blocked: nothing / need interface change for X
```

**Friday:** both devs run `docker compose up` + full integration test. Both check if their parts work together.

### Sprint 0 (Week 1): Foundation

**Dev 1:**
- Review and fix scaffold (pyproject.toml, docker-compose, imports)
- Create CLAUDE.md
- Make `docker compose up` work
- Implement core/config.py fully (validate all settings actually load)
- Set up Alembic — verify migrations run against real PostgreSQL
- Implement auth/jwt.py + auth/rbac.py (already generated, verify they work)
- Write api/app.py — FastAPI app factory, health endpoint working

**Dev 2:**
- Implement storage/postgres.py — connection pool, basic CRUD (users, workspaces)
- Implement storage/qdrant.py — create collection, upsert, search (against real Qdrant)
- Implement storage/memgraph.py — connection, basic entity/relation CRUD (against real Memgraph)
- Implement llm/ollama.py — generate() and embed() (against real Ollama)
- Verify: can embed text, store in Qdrant, retrieve similar

**Friday check:** `docker compose up` → all services running → can create workspace in DB → can embed and search a test document in Qdrant → Ollama answers a test question.

### Sprint 1 (Week 2): First connector + pipeline

**Dev 1:**
- skills/engine.py — load from DB, select, build prompt
- agent/tools.py — tool definitions
- agent/executor.py — verify sandbox works (already generated)
- api/routes/connections.py — CRUD endpoints
- api/routes/sync.py — trigger sync, status
- api/routes/workspaces.py — CRUD
- storage/encryption.py — verify Fernet works for real credentials

**Dev 2:**
- ingestion/pipeline.py — full pipeline: parse → chunk → dedup → embed → store
- connectors/confluence.py — full implementation with pagination, error handling
- ingestion/processors/text.py, pdf.py — basic parsing
- storage/file_store.py — implement fully
- Test: index 50 Confluence pages → search returns relevant results

**Friday check:** POST connection creds via API → trigger sync → Confluence pages indexed in Qdrant → basic search returns relevant chunks.

### Sprint 2 (Week 3): Retrieval quality + more connectors

**Dev 1:**
- agent/router.py — MessageRouter (LLM-as-Router pattern)
- agent/commands.py — all /commands with real responses
- agent/sessions.py — conversation history in PostgreSQL
- api/routes/skills.py — CRUD
- Begin channels/telegram.py

**Dev 2:**
- retrieval/hybrid.py — connect to real Qdrant dense + sparse search
- retrieval/graph_enrichment.py — entity extraction, Memgraph queries
- retrieval/context.py — root-child context assembly
- retrieval/fallback.py — graceful degradation wrapper
- connectors/jira.py, connectors/notion.py
- Test: "Who owns auth module?" → hybrid search → graph enrichment → scored results

**Friday check:** query through Python → full retrieval pipeline → multi-factor scored results → LLM generates answer with sources. 3+ connectors indexing.

### Sprint 3 (Week 4): Telegram + end-to-end

**Dev 1:**
- channels/telegram.py — full implementation, message handling, file uploads
- Wire everything: Telegram message → router → retrieval → LLM → send response
- Commands working in Telegram: /search, /sync, /status, /help
- /connect wizard (interactive credentials setup)

**Dev 2:**
- connectors/github.py, connectors/gdrive.py, connectors/slack_history.py
- observability: wire QueryTrace through entire retrieval pipeline
- api/routes/benchmarker.py — /api/v1/query/trace returning real traces
- Performance: batch embedding, connection pooling

**Friday check:** send message in Telegram → get answer from knowledge base. /sync triggers real connector. /api/v1/query/trace returns 7-step trace.

### Sprint 4 (Week 5): Slack + polish

**Dev 1:**
- channels/slack.py — Socket Mode, events
- Error messages, long message splitting, formatting
- api/routes/files.py — upload endpoint
- Polish: connection status notifications in messenger

**Dev 2:**
- connectors/files.py — PDF/DOCX processing via upload
- Sync logging: sync_logs table filled with real data
- Connector error handling: retry logic, admin notifications
- Cron-based auto-sync (basic scheduler)

**Friday check:** Telegram + Slack both work. File upload → indexed. Benchmarker collects real traces. Sync errors reported properly.

### Sprint 5 (Week 6): Hardening + demo

Both devs: bug fixes, demo prep, documentation, scoring tuning.

---

## How to Work with Claude Code

### Starting a session

Always specify context:
```
I'm working on the Metatron project. Today I'm implementing
the Confluence connector (src/metatron/connectors/confluence.py).
The interface is defined in core/interfaces.py (ConnectorInterface).
The stub already exists with TODOs describing the implementation plan.
```

### Referencing files

```
@src/metatron/core/interfaces.py — show me ConnectorInterface
@src/metatron/connectors/confluence.py — implement the fetch() method
```

### After generating code

Always verify:
```
Run: pytest tests/unit/test_confluence.py
Run: python -c "from metatron.connectors.confluence import ConfluenceConnector; print('OK')"
```

### If Opus generates something that violates rules

Say:
```
This imports from metatron.agent — that's Layer 4. This module is Layer 3.
Layer 3 cannot import from Layer 4. Move the dependency to a parameter or
add an interface to core/interfaces.py.
```

---

## Dev 2 Onboarding

### What Dev 2 needs to start

1. **Access:** Git repo, team chat
2. **Read these files first (in this order, 30 min total):**
   - README.md — what the project is
   - CLAUDE.md — coding rules
   - docs/ARCHITECTURE.md — how components connect
   - core/interfaces.py — all contracts
   - core/models.py — all data structures
3. **Setup:** `docker compose up -d && pip install -e ".[dev]" && pytest`
4. **First task:** implement storage/postgres.py — safest starting point, no dependencies on other devs' work

### Prompt for Dev 2's LLM tool

Dev 2 should create a similar context file for their LLM. If they use Cursor — `.cursorrules` is auto-read. If another tool — paste at session start:

```
I'm working on Metatron, an AI knowledge agent. My area:
storage/, ingestion/, retrieval/, connectors/, llm/.

Project rules are in CLAUDE.md at project root — always follow them.

Key interfaces I implement are in src/metatron/core/interfaces.py.
Data models are in src/metatron/core/models.py.
Config is in src/metatron/core/config.py.

Layer rules: my code (Layers 1-3) can only import from core/ (Layer 0)
and storage/ (Layer 1). Never import from agent/, channels/, api/.

Always use async/await. Always use structlog, never print().
Always use typed exceptions from core/exceptions.py.
```

---

## Git Workflow

### Branches

```
main              — always working, deployable
dev               — integration branch, both devs merge here
feat/confluence   — Dev 2: Confluence connector
feat/telegram     — Dev 1: Telegram channel
feat/retrieval    — Dev 2: retrieval pipeline
feat/agent        — Dev 1: agent router
```

### Rules

- Never push directly to main.
- Merge to dev via PR (even if self-approved — it creates a review point).
- Before merging: `pytest` passes, `docker compose up` works.
- If touching core/interfaces.py — notify the other dev BEFORE pushing.
- Conflict resolution: the person who owns the module resolves conflicts in their files.

### PR size

Small PRs. One module or one feature per PR. Examples:
- "feat/confluence: implement fetch with pagination" — good
- "implement all connectors and retrieval and fix auth" — too big, split it

---

## Communication Protocol

### Daily async update (in team chat)

```
🟢 Done: storage: Qdrant dense search working against real data
🔵 Doing: storage: Memgraph entity CRUD
🔴 Blocked: need Connection model to include last_sync_at field
```

### When you need an interface change

```
@Dev1 I need to add `get_connection_status(connection_id) -> str` to
PostgresStore. This doesn't affect your code. Adding in next commit.

@Dev2 I want to add `max_iterations: int = 5` parameter to
LLMProviderInterface.generate_with_tools(). This changes the interface
you implement in llm/ollama.py. OK?
```

### Weekly sync (Friday, 15 min)

1. Demo what works (screen share, 2 min each)
2. What blocked or surprised
3. Next week priorities
4. Interface changes needed

---

## File Checklist by Sprint

### After Sprint 0 — these files must be FULLY working:

```
✅ pyproject.toml, docker-compose.yml, Dockerfile, Makefile
✅ core/ — all files (config, models, interfaces, exceptions, logging)
✅ storage/encryption.py
✅ auth/jwt.py, auth/rbac.py
✅ observability/tracer.py
✅ ingestion/chunking.py, ingestion/dedup.py
✅ retrieval/hybrid.py (RRF algorithm), retrieval/scoring.py
✅ agent/executor.py
✅ api/app.py + routes/health.py
✅ migrations/versions/001, 002, 003
✅ CLAUDE.md
✅ tests pass for all implemented modules
```

### After Sprint 3 — MVP core working:

```
✅ Everything from Sprint 0
✅ storage/qdrant.py, storage/memgraph.py, storage/postgres.py
✅ storage/file_store.py
✅ ingestion/pipeline.py + processors/
✅ retrieval/ — all files working with real data
✅ connectors/ — Confluence, Jira, Notion, GitHub at minimum
✅ llm/ollama.py
✅ skills/engine.py
✅ agent/router.py, agent/commands.py, agent/sessions.py
✅ channels/telegram.py
✅ api/ — connections, workspaces, sync, skills routes
✅ End-to-end: Telegram question → answer
```

### After Sprint 5 — MVP complete:

```
✅ Everything from Sprint 3
✅ channels/slack.py
✅ connectors/ — + GDrive, Slack history, Files
✅ api/routes/benchmarker.py with real traces
✅ api/routes/files.py
✅ src/metatron/benchmarker/ — full module (schemas, services, db, api)
✅ tests/unit/test_benchmarker_*.py — 7 test files, conftest_benchmarker.py
✅ migrations/versions/005_benchmarker.py
✅ embedding_proxy/ — OpenAI-compatible embedding proxy for benchmarker
✅ Connector error handling, retry, admin notifications
✅ Documentation up to date
✅ Demo scenario working
✅ README ready for public
```