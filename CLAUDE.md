# CLAUDE.md — Project Context for Claude Code

## What is this project?
MTRNIX (Metatron Core) is an open-source enterprise knowledge management system.
It ingests documents from Confluence, Jira, and other sources, builds a knowledge graph,
and answers questions via Telegram/Discord bots using hybrid RAG (dense vectors + BM25 + graph enrichment).

## Tech Stack
- **Language:** Python 3.12+
- **Vector DB:** Qdrant (hybrid dense + sparse/BM25)
- **Graph DB:** Memgraph (knowledge graph, entity relationships)
- **Relational DB:** PostgreSQL (auth, workspaces, sync metadata)
- **LLM Providers:** Ollama (local), DeepSeek, OpenRouter (cloud fallback)
- **Embeddings:** sentence-transformers via Ollama (nomic-embed-text, 768 dims)
- **Bot Framework:** aiogram 3.x (Telegram), discord.py 2.x (Discord)
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
├── connectors/     # Confluence, Jira, Notion, GitHub, etc.
├── llm/            # Multi-provider LLM (Ollama, DeepSeek, OpenRouter)
├── auth/           # JWT, RBAC, user mapping
├── agent/          # Router, sessions, executor, tools
├── channels/       # Telegram, Discord bots, Slack (stub)
├── skills/         # Skill engine (stub)
├── workspaces/     # Multi-tenant workspace management
└── api/            # FastAPI routes
tests/unit/         # pytest — mirrors src/ structure
docs/               # TODO.md, architecture decisions
```

## Architecture Layers (dependency direction: top depends on bottom only)

Layer 0: `core/` — models, interfaces, config, exceptions, logging (ZERO dependencies)
Layer 1: `storage/`, `observability/` — data access (depends on core only)
Layer 2: `ingestion/`, `retrieval/` — document processing, search (depends on core + storage)
Layer 3: `connectors/`, `skills/`, `llm/`, `auth/` — integrations (depends on core + storage + layer 2)
Layer 4: `agent/` — orchestration (depends on core + retrieval + skills + llm)
Layer 5: `channels/` — messengers (depends on core + agent)
Layer 6: `api/` — HTTP endpoints (depends on everything)

NEVER import from a higher layer. If you need something from a higher layer, add an interface to `core/` or pass it as a parameter.

## Search Pipeline (hybrid_search_and_answer)
The main entry point is `retrieval/search.py::hybrid_search_and_answer()`. Flow:
1. `rq = intent_query` (current message for lang detection + person regex)
2. `lang = detect_response_language(rq)` — 30% Cyrillic threshold
3. `eq = expand_query(rq)` — LLM adds BM25 keywords
4. `sq = translate_to_english(eq)` — if Cyrillic
5. **Injection** (`elif` — person XOR activity):
   - `if person` → `search_by_assignee(resolve_person_name(person))`
   - `elif activity` → `search_by_status("In Progress"/"В работе"/...)`
6. `raw = search_with_date_filter(sq, date_query=rq)` — ±7 day widening
7. `raw = merge(injected, raw)`
8. `base = diversify_results(raw)` — min 2 per source type
9. `frags = collect_frags(base)` — `[JIRA]`/`[CONFLUENCE]` labels
10. Graph enrichment via Memgraph
11. LLM answer (prompt has `{response_language}`)
12. `return append_sources(answer, base)` — emoji citations

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
Scopes: core, storage, ingestion, retrieval, connectors, skills, agent, channels, api, auth, observability, infra, docs, tests
Examples:
- `connectors: implement Confluence fetch with pagination`
- `retrieval: add graph enrichment step to hybrid search`
- `infra: fix docker-compose healthcheck for memgraph`

## Running

```bash
# Tests
.venv/bin/pytest tests/ -v --tb=short

# Unified launcher (API + Telegram + Discord bots)
.venv/bin/python -m metatron.app

# API server only
.venv/bin/python -m metatron.api.app
```

## Key Files to Read First

- `core/interfaces.py` — all contracts
- `core/models.py` — all data structures
- `core/config.py` — all settings (env vars)
- `retrieval/search.py` — main search pipeline
- `retrieval/prompts.py` — LLM system prompts
- `agent/router.py` — intent classification + dispatch
- `agent/sessions.py` — conversation history + follow-up detection

## When Creating a New Connector

1. Create `src/metatron/connectors/<name>.py`
2. Implement ConnectorInterface (see `core/interfaces.py`)
3. Register in `connectors/registry.py`
4. Add credentials schema to docstring
5. Write skill .md if connector has action capabilities

## When Modifying Database Schema

1. Create new migration: `alembic revision -m "description"`
2. Write upgrade() and downgrade()
3. Test: `alembic upgrade head` then `alembic downgrade -1` then `alembic upgrade head`
4. Update `core/models.py` if new data structures needed
