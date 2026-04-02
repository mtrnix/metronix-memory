# Storage

## Overview
L1 — database clients. No business logic. Three stores: PostgreSQL (metadata + BM25),
Qdrant (vectors), Neo4j (knowledge graph). All other layers call into storage;
storage never imports upward.

See also: [migrations.md](./migrations.md) — auto-migration on startup.

## Files

### `pg_models.py`
SQLAlchemy ORM models (sync, psycopg2-based).

| ORM Class | Table | Key columns |
|-----------|-------|-------------|
| `WorkspaceRow` | `workspaces` | id, name, slug, is_default, is_active, created_by |
| `UserRow` | `users` | id, email, role, password_hash, last_login_at |
| `WorkspaceMemberRow` | `workspace_members` | workspace_id→FK, user_id→FK, role |
| `ConnectionRow` | `connections` | workspace_id→FK, connector_type, config_encrypted (LargeBinary), status, last_synced_at |
| `ConfigRow` | `config` | workspace_id→FK, key, value (JSON) |
| `SyncLogRow` | `sync_logs` | workspace_id→FK, connection_id→FK, status, documents_fetched/new/updated/skipped, errors (JSONB), duration_ms, qdrant_chunks |
| `QueryTraceRow` | `query_traces` | workspace_id, query, trace (JSONB), total_ms, created_at |

All FKs use `ondelete="CASCADE"`.
`QueryTraceRow.trace` JSONB stores `source_word_count` and other retrieval metadata (see `retrieval/.claude/finops.md`).

### `pg_connection.py`
Sync SQLAlchemy engine + session factory (psycopg2). **TODO: async migration**.

`get_engine(dsn)` — lazy singleton, `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`, `pool_recycle=3600`.
`get_session()` — context manager returning `Session`.
`store_query_trace_sync(workspace_id, query, trace_data, total_ms)` — writes `QueryTraceRow` in a new session.

### `postgres.py`
`PostgresStore` — higher-level PostgreSQL operations.
CRUD for workspaces, users, connections, sync logs, config entries.
Used by workspaces manager, auth user_mapping, connections API.

### `qdrant.py`
`QdrantVectorStore` — wraps qdrant-client.

`get_collection_name(workspace_id) -> str` — `f"metatron_{normalize_workspace_id(workspace_id)}"`.

Key methods:
- `hybrid_search(query, limit, filter_conditions) -> list[dict]` — dense + sparse (BM25) search
- `search_by_doc_labels(labels, limit) -> list[dict]` — fetch chunks by doc label filter
- `upsert_chunks(chunks)` — batch upsert with vectors
- `delete_by_workspace(workspace_id)` — cleanup

`get_hybrid_store(workspace_id) -> QdrantVectorStore` — module-level cache keyed by workspace_id.
`clear_store_cache()` — invalidates store cache (used in tests).

### `neo4j_graph.py`
Neo4j (bolt/neo4j driver) connection and graph operations.

`get_graph_driver(uri, user, password)` — singleton bolt driver.
`graph_retry(max_attempts=3)` — decorator for reconnect on `ServiceUnavailable`.
`extract_graph_from_text(text, max_text_length=8000) -> dict` — LLM-based NER extraction → `{entities: [], relations: []}`.
`write_doc_graph(doc, workspace_id)` — writes Document → Chunk → Entity nodes + relationships.
`delete_workspace_graph(workspace_id)` — removes all nodes for workspace.

### `graph_ops.py`
High-level graph query functions used by retrieval.

`get_graph_entities(frags, workspace_id) -> list[dict]` — entities mentioned in fragments.
`get_graph_relationships(entities, workspace_id, max_depth=2) -> list[dict]` — entity relationships.
`get_doc_labels_by_entities(entities, workspace_id) -> list[str]` — doc labels containing entities.
`get_entities_by_doc_labels(labels, workspace_id) -> list[dict]` — entities in given docs.
`get_related_documents(frags, workspace_id) -> list[str]` — doc labels related to fragment content.
`get_relationships_at_date(entities, date, workspace_id) -> list[dict]` — temporal relationship query.

### `graph_entities.py`
Lower-level Cypher queries for entity/node CRUD.
`merge_entity(name, type, workspace_id)`, `merge_relationship(source, target, rel_type, workspace_id)`.

### `graph_jira.py`
Jira-specific graph schema operations.
`:JiraIssue`, `:Sprint`, `:Person` node types with Jira-specific relationships.

### `dashboard_queries.py`
Aggregation queries for dashboard endpoints.
`get_workspace_overview(workspace_id) -> dict` — document count, chunk count, last sync.
`get_sync_history(workspace_id, limit) -> list[dict]` — recent sync log entries.
`get_graph_lineage(workspace_id) -> dict` — raw_documents → chunks → graph_nodes counts.
`get_orphan_nodes(workspace_id) -> list[dict]` — graph nodes with no edges.

### `encryption.py`
`encrypt(data: bytes, key: str) -> bytes` — Fernet encryption.
`decrypt(data: bytes, key: str) -> bytes` — Fernet decryption.
Used by connections API to protect connector credentials at rest.

### `file_store.py`
`FileStore(base_path)` — local disk storage for uploaded files.
`save(workspace_id, filename, content) -> FileRecord` — writes file, computes SHA-256.
`get_path(file_id) -> Path`, `delete(file_id)`.

### `cleanup.py`
`ALLOW_CLEANUP: bool` — env var guard (`ALLOW_CLEANUP=true` required).
`cleanup_workspace(workspace_id)` — deletes Qdrant collection + Neo4j workspace nodes.
`cleanup_all()` — deletes all workspaces.
`get_cleanup_preview()` — returns counts without deleting.

### `migrate_env_connections.py`
One-time migration: reads legacy env vars (CONFLUENCE_URL, TELEGRAM_BOT_TOKEN, etc.),
groups them by connector type, validates required fields, and creates encrypted DB
connections via `PostgresStore.create_connection()`. Idempotent — skips types that
already exist in the database for the workspace.

`_ENV_MAPPINGS` — maps env var names to `(connector_type, config_field)` tuples.
`_collect_configs_from_env()` — reads env vars, returns `{connector_type: {field: value}}`.
`migrate_env_to_db(postgres_dsn, workspace_id, fernet_key)` — async entry point.
Returns `{"created": [...], "skipped": [...], "errors": [...]}`.

Called automatically at startup in both `app.py` (unified launcher) and `api/app.py`
(lifespan), after Alembic migrations. Safe to run repeatedly.

### `migrations.py`
Auto-run Alembic migrations on startup with PostgreSQL advisory lock.
See [migrations.md](./migrations.md) for full documentation.

## Key Patterns
- **Sync everything** — all storage clients are synchronous (psycopg2, qdrant-client sync, neo4j bolt). Called via `asyncio.to_thread()` from async layers. TODO: async migration.
- **Module-level singletons** — `get_engine()`, `get_hybrid_store()`, `get_graph_driver()` all use lazy module-level caches with thread locks
- **Workspace isolation** — every query scoped by `workspace_id`; Qdrant uses per-workspace collections
- **Fernet encryption** — connector `config_encrypted` is always encrypted before storage, never stored plaintext

## Dependencies
- **Depends on**: `core.models`, `core.config` (Settings DSNs)
- **Depended on by**: `retrieval` (qdrant, graph_ops), `ingestion` (qdrant, neo4j), `workspaces` (postgres), `connectors` (postgres), `auth` (postgres), `api.routes.*` (dashboard_queries, cleanup)
