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