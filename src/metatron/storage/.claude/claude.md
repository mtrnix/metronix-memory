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
| `UserPlatformMappingRow` | `user_platform_mappings` | user_id→FK, platform, platform_user_id, display_name (migration 010) |

Tables managed by migrations (no ORM model):
- `raw_documents` — source of truth for document content (migration 011): workspace_id, source_type, source_id, title, content, content_hash, url, metadata (JSONB), synced_at, graph_synced_at.
  - **Lifecycle columns (migration 018, MTRNIX-313):** `status` (`active`|`candidate`|`stale`|`superseded`|`archived`|`conflicted`|`review_needed`, default `active`, CHECK constraint), `freshness_score` (float, default 0.5), `superseded_by` (text, nullable), `valid_until` (timestamptz, nullable), `evidence_count` (int, default 0), `verification_state` (text, nullable), `last_freshness_run_at` (timestamptz, nullable). Indexes: `ix_raw_docs_ws_status(workspace_id, status)`, partial `ix_raw_docs_ws_valid_until(workspace_id, valid_until) WHERE valid_until IS NOT NULL`.
- `dedup_fingerprints` — persistent SimHash fingerprints (migration 012): workspace_id, doc_label, fingerprint (bigint), chunk_index
- `review_entries` — freshness review queue. Migration 018 renames `record_id → target_id` and adds a `target_kind` discriminator column (`memory_record` | `raw_document`, default `memory_record`). The old `ix_review_entries_record` is replaced by `ix_review_entries_target(workspace_id, target_kind, target_id)`. Phase A subscribers keep working because the dataclass exposes `record_id` as a settable alias of `target_id`.

All FKs use `ondelete="CASCADE"`.
`QueryTraceRow.trace` JSONB stores `source_word_count` and other retrieval metadata (see `retrieval/.claude/finops.md`).

### `pg_connection.py`
Sync SQLAlchemy engine + session factory (psycopg2). **TODO: async migration**.

`get_engine(dsn)` — lazy singleton, `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`, `pool_recycle=3600`.
`get_session()` — context manager returning `Session`.
`store_query_trace_sync(workspace_id, query, trace_data, total_ms)` — writes `QueryTraceRow` in a new session.

### `postgres.py`
`PostgresStore` — higher-level PostgreSQL operations (async, uses asyncpg/aiosqlite).
CRUD for workspaces, users, connections, sync logs, config entries.
Used by workspaces manager, auth user_mapping, connections API.

Raw document methods:
- `upsert_raw_documents(workspace_id, documents)` — insert/update with content_hash comparison
- `get_unsynced_raw_documents(workspace_id)` — documents not yet graph-processed
- `mark_raw_documents_synced(workspace_id, source_ids)` — set graph_synced_at timestamp
- `get_raw_document(workspace_id, source_type, source_id)` — fetch single raw document
- `get_raw_document_by_id(workspace_id, raw_document_id)` — fetch by PK (freshness pipeline uses this)
- `update_raw_document_lifecycle(workspace_id, raw_document_id, *, status?, freshness_score?, superseded_by?, evidence_count?, verification_state?, valid_until?, last_freshness_run_at?, append_tag?)` — partial-update helper used by the `RawDocumentTarget` adapter; only passed-in columns are written (MTRNIX-313).

Dedup fingerprint methods:
- `batch_load_fingerprints(workspace_id) -> dict[int, str]` — load all fingerprints
- `save_fingerprints(workspace_id, fingerprints)` — batch-insert new fingerprints

### `qdrant.py`
Two vector store implementations:

**`QdrantVectorStore`** — sync wrapper around qdrant-client.

`get_collection_name(workspace_id) -> str` — `f"metatron_{normalize_workspace_id(workspace_id)}"`.

Key methods:
- `hybrid_search(query, limit, filter_conditions) -> list[dict]` — dense + sparse (BM25/SPLADE) search
- `dense_search_raw(embedding, limit, filter_conditions) -> list[dict]` — dense-only search
- `sparse_search_raw(sparse_vector, limit, filter_conditions) -> list[dict]` — sparse-only search
- `search_by_doc_labels(labels, limit) -> list[dict]` — fetch chunks by doc label filter
- `upsert_chunks(chunks)` — batch upsert with vectors
- `delete_by_workspace(workspace_id)` — cleanup

`get_hybrid_store(workspace_id) -> QdrantVectorStore` — module-level cache keyed by workspace_id.
`clear_store_cache()` — invalidates store cache (used in tests).

**`AsyncQdrantVectorStore`** — async wrapper using `AsyncQdrantClient`.

Same API surface as sync version but all methods are `async def`.
Key methods: `hybrid_search`, `dense_search`, `keyword_search`, `dense_search_raw`,
`sparse_search_raw`, `add_document`, `search_by_date`, `search_by_type`,
`search_by_doc_labels`, `search_by_status`, `search_by_assignee`, `scroll_by_title`,
`fetch_by_chunk_ids`, `delete_by_doc_labels`, `get_stats`, `close`,
`update_payload_by_doc_label(doc_label, payload)` — bulk-update payload fields
across every chunk for a doc (used by `RawDocumentTarget.sync_downstream_stores`
to mirror `status` / `freshness_score` so retrieval can push the filter down
to Qdrant without a PG round-trip, MTRNIX-313).

Auto-creates Qdrant collection before first ingestion via `_ensure_collection()`.

### `neo4j_graph.py`
Neo4j (bolt/neo4j driver) connection and graph operations.

`get_graph_driver(uri, user, password)` — singleton bolt driver.
`graph_retry(max_attempts=3)` — decorator for reconnect on `ServiceUnavailable`.
`extract_graph_from_text(text, max_text_length=8000) -> dict` — LLM-based NER extraction → `{entities: [], relations: []}`.
`write_doc_graph(doc, workspace_id)` — writes Document → Chunk → Entity nodes + relationships.
`delete_workspace_graph(workspace_id)` — removes all nodes for workspace.
`ensure_graph_indexes()` — creates all Neo4j indexes idempotently (see schema below).

**Neo4j Graph Schema:**

Node types (document ingestion):
- `:User` — uploader (user_id, workspace_id)
- `:Document` — ingested document (doc_id, file_name, workspace_id, doc_label)
- `:Chunk` — document chunk (chunk_id, workspace_id, chunk_type: root|child, doc_label)
- `:Entity` — extracted entity (name, type, workspace_id)
- `:JiraIssue` — Jira issue node (issue_key, workspace_id)
- `:Sprint` — Jira sprint node

Node types (agent memory — WS1):
- `:Agent` — AI agent (id, name, model, workspace_id, created_at)
- `:Session` — agent conversation session (id, agent_id, workspace_id, started_at, ended_at)
- `:MemoryRecord` — agent memory entry (id, workspace_id, agent_id, scope, source_type, tags, ttl_expires_at, created_at). NO content blobs — content lives in Qdrant.

Relationships (document ingestion):
- `(:User)-[:UPLOADED]->(:Document)`
- `(:Document)-[:MENTIONS]->(:Entity)`
- `(:Entity)-[:RELATION {type}]->(:Entity)`
- `(:Entity)-[:ALIAS]->(:Entity)` — person name normalization
- `(:Chunk)-[:CHILD_OF]->(:Chunk)` — root-child hierarchy

Relationships (agent memory — WS1):
- `(:Agent)-[:REMEMBERS]->(:MemoryRecord)`
- `(:MemoryRecord)-[:ABOUT]->(:Entity)`
- `(:MemoryRecord)-[:FROM_SESSION]->(:Session)`
- `(:MemoryRecord)-[:DERIVED_FROM]->(:Document)`

Indexes (created by `ensure_graph_indexes()`):
- `Entity(name)`, `Entity(workspace_id)`
- `Document(doc_label)`, `Document(workspace_id)`
- `JiraIssue(issue_key)`, `JiraIssue(workspace_id)`
- `Agent(workspace_id)`
- `MemoryRecord(workspace_id, scope)` — composite, for scoped memory queries
- `MemoryRecord(ttl_expires_at)` — for TTL cleanup jobs

### `memory_graph.py`
Neo4j graph operations for Agent Memory (WS1). Reuses driver from `neo4j_graph.py`.

Functions:
- `upsert_memory_node(record)` — MERGE MemoryRecord node (metadata only, no content)
- `get_memory_node(workspace_id, record_id) -> dict | None` — fetch single node
- `delete_memory_node(workspace_id, record_id) -> bool` — DETACH DELETE
- `delete_agent_memories(workspace_id, agent_id, scope?) -> int` — bulk delete
- `link_agent_memory(workspace_id, agent_id, record_id)` — MERGE Agent + REMEMBERS edge
- `link_memory_entity(workspace_id, record_id, entity_name, relevance?)` — ABOUT edge
- `link_memory_session(workspace_id, record_id, session_id, agent_id)` — MERGE Session + FROM_SESSION edge
- `link_memory_document(workspace_id, record_id, doc_id)` — DERIVED_FROM edge
- `get_agent_memories(workspace_id, agent_id, scope?, limit?) -> list[dict]` — traverse REMEMBERS
- `get_memories_about_entity(workspace_id, entity_name, limit?) -> list[dict]` — traverse ABOUT
- `get_memory_relationships(workspace_id, record_id) -> list[dict]` — all edges for a memory
- `save_memory_to_graph(record, entity_names?, document_ids?)` — composite: node + all edges

### `raw_document_graph.py`
Neo4j helpers for `:Document` freshness edges (MTRNIX-313). Sync functions,
called via `asyncio.to_thread` from `RawDocumentTarget`. Best-effort — the
adapter swallows failures since the graph is a derived store.

- `link_raw_documents_batch(workspace_id, edges)` — MERGE
  `(:Document)-[:RELATED_TO {score}]->(:Document)` edges across a batch
  (`edges` is a list of `(src_doc_label, dst_doc_label, score)` tuples).
  Workspace-scoped MATCH prevents cross-tenant writes.
- `alias_raw_documents(workspace_id, src_doc_label, dst_doc_label)` — MERGE
  `[:ALIAS]` edge between two `:Document` nodes.
- `set_raw_document_status(workspace_id, doc_label, status)` — set
  `d.status` property on `:Document` for graph-side observability (no index).

### `memory_redis.py`
Redis session cache for Agent Memory (WS1). Wraps existing `RedisStore`.

Key pattern: `mem:{workspace_id}:{session_id}:{record_id}` (records), `mem:{workspace_id}:{session_id}:_index` (ID list).

Class: `RedisSessionCache(store, default_ttl=14400)`
- `cache(workspace_id, session_id, record, ttl_seconds?) -> MemoryRecord` — store with TTL
- `get(workspace_id, session_id, record_id) -> MemoryRecord | None` — fetch single
- `list(workspace_id, session_id) -> list[MemoryRecord]` — all session records
- `invalidate(workspace_id, session_id) -> int` — drop session, return count
- `extend_ttl(workspace_id, session_id, ttl_seconds) -> bool` — refresh TTL

### `memory_qdrant.py`
Qdrant vector store for Agent Memory (WS1). Dedicated collection per workspace.

Collection: `mem_agent_memory_{workspace_id}` (dense 768-dim + sparse SPLADE/BM25).
Payload indexes: `agent_id` (keyword), `scope` (keyword).

Class: `MemoryQdrantStore(workspace_id, host?, port?)`
- `upsert(record)` — embed content + store with vectors and payload. Payload now
  carries `status` (MTRNIX-314) so search-time lifecycle filtering pushes down.
- `search(query, agent_id?, scope?, top_k?, status_exclude?) -> list[dict]` —
  hybrid RRF search (workspace scoped at init). `status_exclude` (MTRNIX-314)
  adds a `must_not` `MatchAny` filter; legacy points without a `status` payload
  are NOT excluded, so missing-as-ACTIVE semantics hold.
- `update_payload(record_id, dict)` — partial payload update without re-embedding.
  Called by `MemoryTarget.sync_downstream_stores` on every worker-driven
  lifecycle transition (MTRNIX-322) to mirror `memory_records.status` onto
  the Qdrant point payload.
- `delete(record_id)` — delete single point
- `delete_by_agent(agent_id)` — delete all points for agent
- `close()` — close client

### `memory_postgres.py`
PostgreSQL store for Agent Memory (WS1). Source of truth for all memory records and snapshots.

Tables: `memory_records` (migration 013), `memory_snapshots` (migration 013).

Class: `MemoryPostgresStore(engine: AsyncEngine)`
- `save(record) -> MemoryRecord` — upsert by id, sets updated_at
- `get(workspace_id, record_id) -> MemoryRecord | None` — fetch by id
- `delete(workspace_id, record_id) -> bool` — delete, returns True if existed
- `list_records(workspace_id, agent_id?, scope?, status?, limit?, offset?) -> list[MemoryRecord]` — filtered list. `status` (MTRNIX-314) adds a `status = ANY(:status_list)` WHERE clause when provided.
- `count_records(workspace_id, agent_id?, scope?, status?) -> int` — same filter surface so pagination `total` matches `list_records`.
- `get_many_statuses(workspace_id, record_ids) -> dict[str, LifecycleStatus]` (MTRNIX-314) — batched status lookup used by the hybrid-search graph-leg post-filter.
- `reset(workspace_id, agent_id?, scope?) -> tuple[int, list[str]]` — DELETE RETURNING id, returns (count, deleted_ids)
- `get_by_hash(workspace_id, agent_id, content_hash) -> MemoryRecord | None` — dedup lookup (ORDER BY created_at DESC)
- `delete_expired(workspace_id) -> int` — TTL cleanup (not yet wired to a periodic trigger)
- `update_lifecycle(...)` — freshness-pipeline partial update for lifecycle columns (status, freshness_score, superseded_by, …).
- `save_snapshot(snapshot) -> MemorySnapshot` — insert snapshot metadata
- `delete_snapshot(workspace_id, snapshot_id) -> bool` — delete, returns True if existed
- `get_snapshot(workspace_id, snapshot_id) -> MemorySnapshot | None`
- `list_snapshots(workspace_id, agent_id) -> list[MemorySnapshot]`

### `freshness_pg.py`
PostgreSQL store for freshness pipeline machinery — review queue (`review_entries`)
and machine-event audit log (`machine_events`). Target-agnostic: every query is
keyed by `(workspace_id, target_kind, target_id)` so the same table serves memory
and KB review items. Renamed from `memory_freshness_pg.py` in MTRNIX-313;
`memory_freshness_pg.py` remains as a thin re-export shim for backward compat.

`FreshnessStore` API:
- `save_review_entry(entry)`, `find_review_entry(...)` — idempotent writes/lookups.
- `list_review_entries(workspace_id, *, record_id?, target_id?, target_kind?, reason?, limit?, offset?) -> list[ReviewEntry]` — paginated list. `reason` and `offset` added in MTRNIX-314.
- `count_review_entries(workspace_id, *, target_kind?, target_id?, record_id?, reason?) -> int` (MTRNIX-314) — companion to `list_review_entries` for pagination.
- `delete_review_entry(workspace_id, review_id) -> bool` (MTRNIX-314) — workspace-scoped delete used by `MemoryService.resolve_review`.
- `save_machine_event(event)`, `list_events_for_target(...)` — audit log ops.

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
- **Async + sync** — PostgresStore is async (asyncpg/aiosqlite), Qdrant has both sync `QdrantVectorStore` and async `AsyncQdrantVectorStore`, Neo4j is sync (neo4j bolt, called via `asyncio.to_thread()`)
- **Module-level singletons** — `get_engine()`, `get_hybrid_store()`, `get_graph_driver()` all use lazy module-level caches with thread locks
- **Workspace isolation** — every query scoped by `workspace_id`; Qdrant uses per-workspace collections
- **Fernet encryption** — connector `config_encrypted` is always encrypted before storage, never stored plaintext

## Dependencies
- **Depends on**: `core.models`, `core.config` (Settings DSNs)
- **Depended on by**: `retrieval` (qdrant, graph_ops), `ingestion` (qdrant, neo4j), `workspaces` (postgres), `connectors` (postgres), `auth` (postgres), `api.routes.*` (dashboard_queries, cleanup)
