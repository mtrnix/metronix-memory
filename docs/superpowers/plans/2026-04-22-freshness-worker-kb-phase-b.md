# Freshness Worker for KB `raw_documents` (Phase B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Phase A freshness pipeline (Linker → Reconciler → FreshnessMonitor → Curator → DecisionEngine) to the KB `raw_documents` surface. Reuse Phase A stage implementations via a `FreshnessTarget` adapter protocol (Option A). Ship schema, worker routing, ingestion producer hook, and search-pipeline filter/scoring integration — each independently feature-flagged so the rollout can stop at any phase without rollback.

**Architecture:** One shared per-workspace Redis queue discriminated by `FreshnessJob.target_kind`. One worker process hosting two pipeline stacks (memory + KB). Five stages retooled to take a `FreshnessTarget` adapter; `MemoryTarget` wraps current Phase A stores, `RawDocumentTarget` wraps new KB stores. Seven lifecycle columns on `raw_documents`, Qdrant payload sync on status changes, optional retrieval filter + scoring signal — both behind their own flags.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy async (asyncpg), `redis.asyncio`, `AsyncQdrantClient`, Neo4j bolt (sync, `asyncio.to_thread`), `llm/provider.py` reused, structlog, pytest (`asyncio_mode = "auto"`).

**Jira:** MTRNIX-313
**Parent ticket:** MTRNIX-304 (Phase A — merged, PR #83).
**Sibling tickets:** MTRNIX-314 (MCP review queue / status filter).
**Spec:** `docs/superpowers/specs/2026-04-22-freshness-worker-kb-phase-b-design.md`
**Branch:** `feature/MTRNIX-313`

---

## Layer Boundary Summary

| File | Layer | Allowed imports |
|---|---|---|
| `core/models.py` (extend) | L0 | stdlib only |
| `core/config.py` (extend) | L0 | pydantic-settings |
| `freshness/targets.py` (new) | L2 | `core.models`, stdlib typing |
| `freshness/coordination.py` (moved from memory/) | L2 | `core.config`, `storage.redis` |
| `freshness/decision_engine.py` (moved from memory/) | L2 | `core`, `llm.provider` |
| `freshness/metrics.py` (moved from memory/) | L2 | stdlib, `prometheus_client` (try/except) |
| `freshness/stages/linker.py` (refactored generic) | L2 | `core`, `freshness.targets`, `freshness.coordination` |
| `freshness/stages/reconciler.py` (refactored generic) | L2 | same |
| `freshness/stages/monitor.py` (refactored generic) | L2 | same |
| `freshness/stages/curator.py` (refactored generic) | L2 | same |
| `freshness/apply_decision.py` (extracted) | L2 | `core.models`, `freshness.targets` |
| `memory/freshness/*` (re-export shims only) | L3 | `metatron.freshness.*` |
| `memory/freshness/target_memory.py` (new adapter) | L3 | `core.models`, `storage.memory_*` |
| `ingestion/freshness/producer.py` (new) | L2 | `core.config`, `freshness.coordination` |
| `ingestion/freshness/target_raw_document.py` (new adapter) | L2 | `core.models`, `storage.postgres`, `storage.qdrant`, `storage.raw_document_graph` |
| `storage/postgres.py` (extend) | L1 | SQLAlchemy async |
| `storage/qdrant.py` (extend: `update_payload_by_doc_label`) | L1 | `AsyncQdrantClient` |
| `storage/raw_document_graph.py` (new) | L1 | `storage.neo4j_graph` |
| `storage/memory_freshness_pg.py` → renamed `storage/freshness_pg.py` | L1 | SQLAlchemy async |
| `retrieval/search.py` (extend) | L2 | `core.config`, `storage.postgres` |
| `retrieval/channels.py` (extend) | L2 | `qdrant_client.http.models` |
| `retrieval/scoring.py` (extend) | L2 | stdlib math |
| `migrations/versions/018_kb_freshness_lifecycle.py` (new) | — | alembic |

**Not touched:** `agent/`, `channels/`, `api/routes/chat.py`, `api/routes/finops.py`, `skills/`, `workspaces/`, `core/interfaces.py`, `core/events.py`.

**No upward imports.** The new `src/metatron/freshness/` subtree sits at L2 (same level as `ingestion/` and `retrieval/`). Memory's L3 adapter imports down into L2 (allowed). KB's adapter is inside `ingestion/freshness/` (L2) — imports from `storage/` (L1) and `core/` (L0).

---

## Config Vars (all with `METATRON_` prefix, added to `src/metatron/core/config.py`)

| Env var | Settings field | Default | Purpose |
|---|---|---|---|
| `METATRON_FRESHNESS_KB_ENABLED` | `freshness_kb_enabled` | `False` | Gates the KB producer. When `False`: `enqueue_raw_document_if_enabled` is a no-op. Master flag `freshness_enabled` must also be `True` for KB jobs to be enqueued. |
| `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED` | `freshness_kb_search_filter_enabled` | `False` | Gates the retrieval-side ARCHIVED/SUPERSEDED filter. When `False`: search behaves byte-identical to today. |
| `METATRON_FRESHNESS_WEIGHT` | `freshness_weight` | `0.0` | New scoring-signal weight. When `0.0`: `compute_signal_score` is numerically identical to today. |
| `METATRON_FRESHNESS_KB_STALE_AFTER_DAYS` | `freshness_kb_stale_after_days` | `90` | KB-specific stale threshold (docs age slower than memory; default differs from `freshness_stale_after_days=30`). |

Reused from Phase A: all other `FRESHNESS_*` env vars (`FRESHNESS_ENABLED`, `FRESHNESS_POLL_SECONDS`, `FRESHNESS_LOCK_TTL_SECONDS`, `FRESHNESS_DECISION_CONFIDENCE_THRESHOLD`, `FRESHNESS_LLM_*`, `FRESHNESS_LINKER_THRESHOLD`, `FRESHNESS_RECONCILER_THRESHOLD`, `FRESHNESS_BACKOFF_*`, `FRESHNESS_MAX_CONSECUTIVE_ERRORS`, `FRESHNESS_MAX_JOBS_PER_ITERATION`).

---

## Event Constants

**No new constants.** Reuse Phase A's four: `FRESHNESS_JOB_ENQUEUED`, `FRESHNESS_JOB_PROCESSED`, `FRESHNESS_DECISION_APPLIED`, `FRESHNESS_REVIEW_CREATED`. Payloads already include `target_kind` via the job. KB jobs emit the same event names with `target_kind="raw_document"`.

**ENTERPRISE COORDINATION COURTESY:** the PR description must flag that subscribers will now see both `target_kind="memory_record"` and `target_kind="raw_document"` events after Phase B. Subscribers that only want memory events should filter on the payload's `target_kind`. No breaking change; additive only.

---

## Backward Compatibility Guarantee

When all three KB flags are `False` (the default):
- `PostgresStore.upsert_raw_documents` behaviour is unchanged except that the new lifecycle columns get their DB-default values on INSERT. No code path reads the new columns yet.
- `api/routes/connections.py::_run_connection_sync` calls the new producer, which short-circuits — zero Redis traffic.
- `retrieval/search.py` sees no `freshness_filter` (flag off) and `freshness_weight=0.0` in scoring — formula numerically identical to today.
- `FreshnessWorker` (from Phase A) is unchanged externally. Internally it gains a `target_kind` switch but the memory path is byte-identical.
- All Phase A memory-freshness tests stay green (explicit regression guard in Task 7).
- Existing 1150+ tests pass.
- Alembic migration 018 is backward-compatible on existing data: all rows get `status='active'`, `freshness_score=0.5`, everything else NULL/0.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `src/metatron/core/models.py` | Promote `MemoryStatus` → `LifecycleStatus` (keep `MemoryStatus` as alias). Add `target_kind` field to `ReviewEntry`. Extend `RawDocument` with 7 lifecycle fields + `last_freshness_run_at`. |
| Modify | `src/metatron/core/config.py` | Add 4 new KB-specific config vars. |
| Create | `migrations/versions/018_kb_freshness_lifecycle.py` | ALTER `raw_documents` (7 cols + indexes); RENAME `review_entries.record_id → target_id`; ADD `review_entries.target_kind`. |
| Create | `src/metatron/freshness/__init__.py` | Re-export `CoordinationStore`, `FreshnessTarget`, `DecisionEngine`, `build_default_decision_engine`, `metrics`. |
| Create | `src/metatron/freshness/targets.py` | `FreshnessTarget` Protocol + `FreshnessTargetRecord` DTO + `SimilarityHit` DTO. |
| Move | `src/metatron/freshness/coordination.py` | Moved from `memory/freshness/coordination.py`. Lock key builder gains optional `target_kind` prefix with backward-compat behaviour for memory. |
| Move | `src/metatron/freshness/decision_engine.py` | Moved from `memory/freshness/decision_engine.py`. Extract `apply_decision` into sibling file. |
| Create | `src/metatron/freshness/apply_decision.py` | Extract `apply_decision` so it takes a `FreshnessTarget` instead of `MemoryPostgresStore`. |
| Move | `src/metatron/freshness/metrics.py` | Moved from `memory/freshness/metrics.py`. Optional `target_kind` label on counters. |
| Create | `src/metatron/freshness/stages/__init__.py` | Package marker. |
| Move | `src/metatron/freshness/stages/linker.py` | Generic `Linker` taking `FreshnessTarget`. |
| Move | `src/metatron/freshness/stages/reconciler.py` | Generic `Reconciler`. |
| Move | `src/metatron/freshness/stages/monitor.py` | Generic `FreshnessMonitor` with age-gate via `last_freshness_run_at`. |
| Move | `src/metatron/freshness/stages/curator.py` | Generic `Curator` honouring `supports_candidate_promotion`. |
| Modify | `src/metatron/memory/freshness/__init__.py` | Re-export shims (one-liners) from `metatron.freshness.*` to preserve existing import paths. |
| Create | `src/metatron/memory/freshness/target_memory.py` | `MemoryTarget` adapter implementing `FreshnessTarget` over `MemoryPostgresStore` + `MemoryQdrantStore` + memory_graph. |
| Delete | `src/metatron/memory/freshness/{linker,reconciler,monitor,curator,coordination,decision_engine,metrics}.py` | Replaced by re-export shims in `__init__.py`. |
| Keep | `src/metatron/memory/freshness/producer.py` | Unchanged (memory producer stays memory-specific). |
| Keep | `src/metatron/memory/freshness/worker.py` | Refactored to build both pipelines and switch on `target_kind`. |
| Keep | `src/metatron/memory/freshness/__main__.py` | Unchanged. |
| Create | `src/metatron/ingestion/freshness/__init__.py` | Package marker. |
| Create | `src/metatron/ingestion/freshness/producer.py` | `enqueue_raw_document_if_enabled(...)` — no-op when flags off; fail-soft on Redis. |
| Create | `src/metatron/ingestion/freshness/target_raw_document.py` | `RawDocumentTarget` adapter (PG + Qdrant + Neo4j for raw_documents). |
| Modify | `src/metatron/storage/postgres.py` | Add `update_raw_document_lifecycle(ws, raw_doc_id, *, status=..., freshness_score=..., ..., last_freshness_run_at=...)`. Extend `get_raw_document` / row mapper to read new columns. |
| Modify | `src/metatron/storage/qdrant.py` | Add `AsyncQdrantVectorStore.update_payload_by_doc_label(ws, doc_label, payload)`. |
| Create | `src/metatron/storage/raw_document_graph.py` | Neo4j helpers for `(:Document)-[:RELATED_TO]->(:Document)` and `(:Document)-[:ALIAS]->(:Document)`. |
| Rename | `src/metatron/storage/memory_freshness_pg.py` → `src/metatron/storage/freshness_pg.py` | Rename class `FreshnessPostgresStore` → `FreshnessStore`. Add `target_kind` plumbing to `save_review_entry` + `find_review_entry`. Keep a compat shim at the old path. |
| Modify | `src/metatron/memory/freshness/worker.py` | Build both `MemoryTarget` and `RawDocumentTarget`; wrap stages; dispatch on `target_kind` in `_process_job`. |
| Modify | `src/metatron/api/routes/connections.py` | After `upsert_raw_documents` succeeds, loop over `changed_source_ids`, resolve each to `raw_documents.id`, call `enqueue_raw_document_if_enabled`. Flag-gated. |
| Modify | `src/metatron/retrieval/search.py` | Build `freshness_filter` alongside `access_filter` (flag-gated). Batch-fetch `raw_documents.freshness_score` for top-35 pool; pass into `compute_signal_score` (weight-gated). |
| Modify | `src/metatron/retrieval/channels.py` | Thread `freshness_filter` through `RecallContext`; combine with `access_filter` in each channel. `recall_metadata_async` gains `exclude_archived=True` default. `recall_graph_async` post-filters doc_labels against PG status. |
| Modify | `src/metatron/retrieval/scoring.py` | Add `freshness: float = 1.0`, `freshness_weight: float = 0.0` params. Adjust `weight_sum` normalization. |
| Create | `tests/unit/freshness/__init__.py` | Package marker. |
| Create | `tests/unit/freshness/test_targets_protocol.py` | Protocol conformance tests for both adapters. |
| Create | `tests/unit/freshness/stages/__init__.py` | Package marker. |
| Create | `tests/unit/freshness/stages/test_linker_with_adapter.py` | Stage generic over both adapters. |
| Create | `tests/unit/freshness/stages/test_reconciler_with_adapter.py` | Same. |
| Create | `tests/unit/freshness/stages/test_monitor_with_adapter.py` | Age-gate + KB stale-after-days behaviour. |
| Create | `tests/unit/freshness/stages/test_curator_with_adapter.py` | Memory promotes; KB no-op (supports_candidate_promotion=False). |
| Keep | `tests/unit/memory/freshness/test_*.py` | Phase A tests — updated imports where necessary, but the suite must remain green as a regression guard. |
| Create | `tests/unit/memory/freshness/test_target_memory.py` | `MemoryTarget` adapter unit tests. |
| Create | `tests/unit/ingestion/freshness/__init__.py` | Package marker. |
| Create | `tests/unit/ingestion/freshness/test_producer_raw_document.py` | Producer on/off + Redis fail-soft. |
| Create | `tests/unit/ingestion/freshness/test_target_raw_document.py` | `RawDocumentTarget` adapter unit tests. |
| Create | `tests/unit/storage/test_raw_documents_lifecycle.py` | `update_raw_document_lifecycle` + row mapper for new columns. |
| Create | `tests/unit/storage/test_qdrant_update_payload.py` | `update_payload_by_doc_label` with `AsyncQdrantClient` mocked. |
| Create | `tests/unit/retrieval/test_freshness_filter.py` | Flag-off → no Filter added; flag-on → Filter combined with `access_filter`. |
| Create | `tests/unit/retrieval/test_scoring_with_freshness.py` | weight=0.0 numerically identical to today. |
| Create | `tests/integration/ingestion/freshness/__init__.py` | Package marker. |
| Create | `tests/integration/ingestion/freshness/test_end_to_end_raw_document.py` | Ingest → enqueue → worker run_once → PG transitions + MachineEvent + Qdrant payload + Neo4j edge. |
| Create | `tests/integration/retrieval/test_search_with_freshness_filter.py` | Two docs, one ARCHIVED; flag-on excludes. |
| Modify | `src/metatron/memory/.claude/CLAUDE.md` | (Documenter step only, post-approval.) |
| Modify | `src/metatron/retrieval/.claude/claude.md` | (Documenter step.) |
| Modify | `src/metatron/ingestion/.claude/claude.md` | (Documenter step.) |
| Modify | `src/metatron/storage/.claude/claude.md` | (Documenter step.) |
| Modify | `CLAUDE.md` (root) | (Documenter step.) |
| Modify | `CHANGELOG.md` | (Documenter step.) |

---

## Ordered Tasks

Execute in order. After **every** task, run `make lint && make typecheck && make test` as separate commands. Run `make eval-compare` at Task 14 (pre-flight).

---

### Task 1: Data model — promote `MemoryStatus` → `LifecycleStatus`, extend `RawDocument`, extend `ReviewEntry`

**Files:**
- Modify: `src/metatron/core/models.py`
- Modify: `src/metatron/core/config.py`

- [ ] **Step 1: Rename `MemoryStatus` → `LifecycleStatus` with backward-compat alias.**

In `core/models.py`, find the `MemoryStatus` enum definition. Change the class name to `LifecycleStatus` and add a bottom-of-section alias:

```python
class LifecycleStatus(StrEnum):
    """Lifecycle status shared by MemoryRecord (agent memory) and RawDocument (KB)."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    CONFLICTED = "conflicted"
    REVIEW_NEEDED = "review_needed"


# Backward compatibility — existing imports `from metatron.core.models import MemoryStatus`
# keep working. Do NOT remove; used by Phase A call sites and enterprise plugin.
MemoryStatus = LifecycleStatus
```

Find every existing reference to `MemoryStatus` in the file — if the dataclass `MemoryRecord` uses `MemoryStatus.ACTIVE` in its default field value, leave it; the alias resolves identically.

- [ ] **Step 2: Extend `RawDocument` with 7 lifecycle fields + `last_freshness_run_at`.**

Find the `@dataclass class RawDocument:` block (around line 55–75). After `updated_at: datetime | None = None` add:

```python
    # --- Freshness lifecycle (MTRNIX-313, Phase B) ---
    status: LifecycleStatus = LifecycleStatus.ACTIVE
    freshness_score: float = 0.5
    superseded_by: str | None = None
    valid_until: datetime | None = None
    evidence_count: int = 0
    verification_state: str | None = None
    last_freshness_run_at: datetime | None = None
```

- [ ] **Step 3: Extend `ReviewEntry` with `target_kind` + rename `record_id` → `target_id` (with alias).**

Find the `ReviewEntry` dataclass. Replace:

```python
    record_id: str = ""
```

with:

```python
    target_id: str = ""
    target_kind: str = "memory_record"
    # --- Backward compatibility (MTRNIX-313): Phase A called this ``record_id``.
    # New code should use ``target_id``. ``record_id`` remains a settable alias
    # during the deprecation window; ``__post_init__`` mirrors the two fields.
    record_id: str = ""

    def __post_init__(self) -> None:
        if self.target_id and not self.record_id:
            self.record_id = self.target_id
        elif self.record_id and not self.target_id:
            self.target_id = self.record_id
```

- [ ] **Step 4: Add 4 new config vars to `core/config.py`.**

Find the existing `METATRON_FRESHNESS_*` settings (around the end of `Settings`). Append:

```python
    freshness_kb_enabled: bool = Field(
        default=False,
        description="KB-side freshness producer flag. Requires freshness_enabled=True.",
    )
    freshness_kb_search_filter_enabled: bool = Field(
        default=False,
        description="Retrieval-side ARCHIVED/SUPERSEDED filter flag.",
    )
    freshness_weight: float = Field(
        default=0.0,
        description="Scoring weight for the freshness signal. 0.0 = off.",
    )
    freshness_kb_stale_after_days: int = Field(
        default=90,
        description="KB stale threshold in days (default 90 vs. memory's 30).",
    )
```

- [ ] **Step 5: Verify imports.**

Run:

```
python -c "from metatron.core.models import LifecycleStatus, MemoryStatus, RawDocument, ReviewEntry; r = ReviewEntry(target_id='x'); print(r.record_id, r.target_kind)"
python -c "from metatron.core.config import Settings; s = Settings(); print(s.freshness_kb_enabled, s.freshness_weight, s.freshness_kb_stale_after_days)"
```

Expected:
- Line 1 prints `x memory_record`.
- Line 2 prints `False 0.0 90`.

- [ ] **Step 6: Run tests.**

Run: `make test`
Expected: all Phase A tests still green. No new tests yet.

- [ ] **Step 7: Commit.**

```
git add src/metatron/core/models.py src/metatron/core/config.py
git commit -m "feat(MTRNIX-313): promote LifecycleStatus, extend RawDocument + ReviewEntry, add KB config"
```

**Acceptance:** `MemoryStatus` is still importable (alias); `RawDocument` has 7 new fields; `ReviewEntry` has `target_id` + `target_kind` with `record_id` as compat alias; 4 new config vars available.

---

### Task 2: Alembic migration 018 — raw_documents lifecycle columns + review_entries column rename

**Files:**
- Create: `migrations/versions/018_kb_freshness_lifecycle.py`

Revision chain: `down_revision = "017"` (latest), `revision = "018"`.

- [ ] **Step 1: Write migration.**

```python
"""Freshness lifecycle columns on raw_documents + review_entries target_kind/target_id (MTRNIX-313).

Revision ID: 018
Revises: 017
Create Date: 2026-04-22
"""
from __future__ import annotations
from typing import TYPE_CHECKING
import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- raw_documents lifecycle columns ---
    op.add_column("raw_documents", sa.Column("status", sa.Text, nullable=False, server_default="active"))
    op.create_check_constraint(
        "ck_raw_docs_status",
        "raw_documents",
        "status IN ('candidate','active','stale','superseded','archived','conflicted','review_needed')",
    )
    op.add_column(
        "raw_documents",
        sa.Column("freshness_score", sa.Float, nullable=False, server_default=sa.text("0.5")),
    )
    op.add_column("raw_documents", sa.Column("superseded_by", sa.Text, nullable=True))
    op.add_column("raw_documents", sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "raw_documents",
        sa.Column("evidence_count", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.add_column("raw_documents", sa.Column("verification_state", sa.Text, nullable=True))
    op.add_column(
        "raw_documents",
        sa.Column("last_freshness_run_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_raw_docs_ws_status", "raw_documents", ["workspace_id", "status"])
    op.create_index(
        "ix_raw_docs_ws_valid_until",
        "raw_documents",
        ["workspace_id", "valid_until"],
        postgresql_where=sa.text("valid_until IS NOT NULL"),
    )

    # --- review_entries: add target_kind, rename record_id → target_id ---
    op.add_column(
        "review_entries",
        sa.Column("target_kind", sa.Text, nullable=False, server_default="memory_record"),
    )
    # Rename column atomically. Older indexes may depend on record_id; list them explicitly.
    op.drop_index("ix_review_entries_record", table_name="review_entries")
    op.alter_column("review_entries", "record_id", new_column_name="target_id")
    op.create_index(
        "ix_review_entries_target",
        "review_entries",
        ["workspace_id", "target_kind", "target_id"],
    )


def downgrade() -> None:
    # --- review_entries rollback ---
    op.drop_index("ix_review_entries_target", table_name="review_entries")
    op.alter_column("review_entries", "target_id", new_column_name="record_id")
    op.create_index("ix_review_entries_record", "review_entries", ["workspace_id", "record_id"])
    op.drop_column("review_entries", "target_kind")

    # --- raw_documents rollback ---
    op.drop_index("ix_raw_docs_ws_valid_until", table_name="raw_documents")
    op.drop_index("ix_raw_docs_ws_status", table_name="raw_documents")
    op.drop_column("raw_documents", "last_freshness_run_at")
    op.drop_column("raw_documents", "verification_state")
    op.drop_column("raw_documents", "evidence_count")
    op.drop_column("raw_documents", "valid_until")
    op.drop_column("raw_documents", "superseded_by")
    op.drop_column("raw_documents", "freshness_score")
    op.drop_constraint("ck_raw_docs_status", "raw_documents", type_="check")
    op.drop_column("raw_documents", "status")
```

- [ ] **Step 2: Dry-run upgrade.**

Run: `alembic upgrade head --sql > /tmp/018.sql`
Then: `head -80 /tmp/018.sql`
Expected: ALTER TABLE statements for `raw_documents` + `review_entries`; check constraint; indexes.

- [ ] **Step 3: Apply on a real DB.**

Run: `make migrate`
Then:
```
psql "$METATRON_POSTGRES_DSN" -c "\d raw_documents" | grep -E "status|freshness_score|evidence_count|last_freshness_run_at"
psql "$METATRON_POSTGRES_DSN" -c "\d review_entries" | grep -E "target_id|target_kind"
```
Expected: all 7 lifecycle columns visible on `raw_documents`; `target_id` + `target_kind` on `review_entries`.

- [ ] **Step 4: Round-trip test.**

Run: `alembic downgrade -1`
Then: `alembic upgrade head`
Expected: both commands succeed. Downgrade deletes the columns; upgrade re-creates them with defaults.

- [ ] **Step 5: Run tests.**

Run: `make test`
Expected: all existing tests still green.

- [ ] **Step 6: Commit.**

```
git add migrations/versions/018_kb_freshness_lifecycle.py
git commit -m "feat(MTRNIX-313): alembic 018 — raw_documents lifecycle columns + review_entries rename"
```

**Acceptance:** Migration applies on empty DB and on populated DB. Round-trip downgrade+upgrade passes. Existing `raw_documents` rows land with `status='active'` / `freshness_score=0.5`. Existing `review_entries` rows get `target_kind='memory_record'` and their `record_id` becomes `target_id`.

---

### Task 3: Storage — `PostgresStore.update_raw_document_lifecycle` + row mapper + `AsyncQdrantVectorStore.update_payload_by_doc_label` + `raw_document_graph` helpers

**Files:**
- Modify: `src/metatron/storage/postgres.py`
- Modify: `src/metatron/storage/qdrant.py`
- Create: `src/metatron/storage/raw_document_graph.py`
- Create: `tests/unit/storage/test_raw_documents_lifecycle.py`
- Create: `tests/unit/storage/test_qdrant_update_payload.py`

- [ ] **Step 1: Extend `PostgresStore` row mapper for `raw_documents`.**

In `src/metatron/storage/postgres.py`, find `get_raw_document` and any row-to-`RawDocument` conversion. Update to SELECT the 7 new columns and populate them on `RawDocument`. The SELECT typically uses `SELECT *` so the column list is implicit; confirm the row mapper's field assignment.

- [ ] **Step 2: Write the unit test for `update_raw_document_lifecycle`.**

`tests/unit/storage/test_raw_documents_lifecycle.py`:

```python
"""Unit tests for PostgresStore.update_raw_document_lifecycle (MTRNIX-313)."""
from __future__ import annotations

import pytest

from metatron.core.models import LifecycleStatus


pytestmark = pytest.mark.asyncio


async def test_update_lifecycle_status_only(pg_store_with_raw_doc) -> None:
    store, workspace_id, raw_doc_id = pg_store_with_raw_doc
    await store.update_raw_document_lifecycle(
        workspace_id, raw_doc_id, status=LifecycleStatus.STALE,
    )
    row = await store.get_raw_document_by_id(workspace_id, raw_doc_id)
    assert row.status == LifecycleStatus.STALE


async def test_update_lifecycle_all_fields(pg_store_with_raw_doc) -> None:
    store, workspace_id, raw_doc_id = pg_store_with_raw_doc
    await store.update_raw_document_lifecycle(
        workspace_id, raw_doc_id,
        status=LifecycleStatus.SUPERSEDED,
        freshness_score=0.1,
        superseded_by="new-doc-id",
        evidence_count=3,
        verification_state="llm_verified",
    )
    row = await store.get_raw_document_by_id(workspace_id, raw_doc_id)
    assert row.status == LifecycleStatus.SUPERSEDED
    assert row.freshness_score == 0.1
    assert row.superseded_by == "new-doc-id"
    assert row.evidence_count == 3
    assert row.verification_state == "llm_verified"


async def test_update_lifecycle_workspace_isolated(pg_store_two_workspaces) -> None:
    """Updating in workspace_a must not touch an identical id in workspace_b."""
    store, ws_a, ws_b, raw_doc_id = pg_store_two_workspaces
    await store.update_raw_document_lifecycle(ws_a, raw_doc_id, status=LifecycleStatus.STALE)
    row_a = await store.get_raw_document_by_id(ws_a, raw_doc_id)
    row_b = await store.get_raw_document_by_id(ws_b, raw_doc_id)
    assert row_a.status == LifecycleStatus.STALE
    assert row_b.status == LifecycleStatus.ACTIVE
```

(Fixtures `pg_store_with_raw_doc` and `pg_store_two_workspaces` go in the file — seed a `raw_documents` row under one or two workspace ids before yielding.)

- [ ] **Step 3: Run the test — expect failure.**

Run: `pytest tests/unit/storage/test_raw_documents_lifecycle.py -v`
Expected: FAIL with `AttributeError: 'PostgresStore' object has no attribute 'update_raw_document_lifecycle'` or `get_raw_document_by_id`.

- [ ] **Step 4: Implement `update_raw_document_lifecycle` + `get_raw_document_by_id`.**

In `src/metatron/storage/postgres.py` (after `upsert_raw_documents`, before `get_unsynced_documents`):

```python
async def get_raw_document_by_id(
    self, workspace_id: str, raw_doc_id: str,
) -> RawDocument | None:
    """Fetch a raw_document row by (workspace_id, id) — freshness-path lookup."""
    async with self._engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT * FROM raw_documents
                WHERE workspace_id = :workspace_id AND id = :id
            """),
            {"workspace_id": workspace_id, "id": raw_doc_id},
        )
        row = result.first()
        return self._row_to_raw_document(row) if row else None


async def update_raw_document_lifecycle(
    self,
    workspace_id: str,
    raw_doc_id: str,
    *,
    status: LifecycleStatus | None = None,
    freshness_score: float | None = None,
    superseded_by: str | None = None,
    evidence_count: int | None = None,
    verification_state: str | None = None,
    valid_until: datetime | None = None,
    last_freshness_run_at: datetime | None = None,
) -> None:
    """Update lifecycle columns on a raw_documents row (workspace-scoped)."""
    updates: dict[str, object] = {}
    if status is not None:
        updates["status"] = status.value
    if freshness_score is not None:
        updates["freshness_score"] = freshness_score
    if superseded_by is not None:
        updates["superseded_by"] = superseded_by
    if evidence_count is not None:
        updates["evidence_count"] = evidence_count
    if verification_state is not None:
        updates["verification_state"] = verification_state
    if valid_until is not None:
        updates["valid_until"] = valid_until
    if last_freshness_run_at is not None:
        updates["last_freshness_run_at"] = last_freshness_run_at
    if not updates:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    async with self._engine.begin() as conn:
        await conn.execute(
            text(
                f"UPDATE raw_documents SET {set_clause} "
                "WHERE workspace_id = :workspace_id AND id = :id"
            ),
            {**updates, "workspace_id": workspace_id, "id": raw_doc_id},
        )
```

Add a `_row_to_raw_document` helper if one doesn't already exist. It must read the 7 new columns plus the existing ones and construct a `RawDocument`.

- [ ] **Step 5: Run tests — expect pass.**

Run: `pytest tests/unit/storage/test_raw_documents_lifecycle.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Add `AsyncQdrantVectorStore.update_payload_by_doc_label`.**

In `src/metatron/storage/qdrant.py`, find `AsyncQdrantVectorStore`. Add the method:

```python
async def update_payload_by_doc_label(
    self,
    workspace_id: str,
    doc_label: str,
    payload: dict[str, object],
) -> None:
    """Set payload fields on every chunk with matching doc_label.

    Used by the freshness worker to mirror ``raw_documents.status`` and
    ``raw_documents.freshness_score`` onto chunk payloads so retrieval can
    push the filter down to Qdrant. Best-effort: failures log + return.
    """
    from qdrant_client.http.models import FieldCondition, Filter, MatchValue

    collection = self._get_collection_name()
    flt = Filter(
        must=[
            FieldCondition(key="doc_label", match=MatchValue(value=doc_label)),
            FieldCondition(key="workspace_id", match=MatchValue(value=workspace_id)),
        ]
    )
    try:
        await self._client.set_payload(
            collection_name=collection,
            payload=dict(payload),
            points=None,
            filter=flt,
            wait=False,
        )
    except Exception:
        logger.warning(
            "qdrant.update_payload.failed",
            workspace_id=workspace_id,
            doc_label=doc_label,
            exc_info=True,
        )
```

- [ ] **Step 7: Write unit test for `update_payload_by_doc_label`.**

`tests/unit/storage/test_qdrant_update_payload.py`:

```python
"""Unit tests for AsyncQdrantVectorStore.update_payload_by_doc_label (MTRNIX-313)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.asyncio


async def test_update_payload_calls_set_payload_with_doc_label_filter() -> None:
    from metatron.storage.qdrant import AsyncQdrantVectorStore

    store = AsyncQdrantVectorStore(workspace_id="ws-1")
    store._client = AsyncMock()
    store._client.set_payload = AsyncMock()
    await store.update_payload_by_doc_label(
        workspace_id="ws-1",
        doc_label="doc-42",
        payload={"status": "archived", "freshness_score": 0.0},
    )
    store._client.set_payload.assert_awaited_once()
    kwargs = store._client.set_payload.await_args.kwargs
    assert kwargs["payload"] == {"status": "archived", "freshness_score": 0.0}
    assert kwargs["wait"] is False


async def test_update_payload_swallows_qdrant_errors() -> None:
    from metatron.storage.qdrant import AsyncQdrantVectorStore

    store = AsyncQdrantVectorStore(workspace_id="ws-1")
    store._client = AsyncMock()
    store._client.set_payload = AsyncMock(side_effect=RuntimeError("qdrant down"))
    # Must not raise.
    await store.update_payload_by_doc_label(
        workspace_id="ws-1", doc_label="doc-42", payload={"status": "archived"},
    )
```

Run: `pytest tests/unit/storage/test_qdrant_update_payload.py -v`
Expected: PASS.

- [ ] **Step 8: Create `storage/raw_document_graph.py`.**

```python
"""Neo4j helpers for :Document freshness graph edges (MTRNIX-313).

Mirrors ``storage/memory_graph.py`` shape: sync functions called via
``asyncio.to_thread`` by the freshness pipeline. Best-effort — all callers
wrap in try/except and NEVER surface failures.
"""

from __future__ import annotations

import structlog

from metatron.storage.neo4j_graph import get_graph_driver

logger = structlog.get_logger()


def link_raw_documents_batch(
    workspace_id: str,
    edges: list[tuple[str, str, float]],
) -> None:
    """Create (:Document)-[:RELATED_TO {score}]->(:Document) edges in one session."""
    if not edges:
        return
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            """
            UNWIND $edges AS e
            MATCH (a:Document {doc_label: e.src, workspace_id: $ws})
            MATCH (b:Document {doc_label: e.dst, workspace_id: $ws})
            MERGE (a)-[r:RELATED_TO]->(b)
            SET r.score = e.score
            """,
            {"ws": workspace_id, "edges": [{"src": s, "dst": d, "score": sc} for s, d, sc in edges]},
        )


def alias_raw_documents(
    workspace_id: str,
    source_doc_label: str,
    target_doc_label: str,
) -> None:
    """Create (or merge) an :ALIAS edge between two :Document nodes."""
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            """
            MATCH (a:Document {doc_label: $src, workspace_id: $ws})
            MATCH (b:Document {doc_label: $dst, workspace_id: $ws})
            MERGE (a)-[:ALIAS]->(b)
            """,
            {"src": source_doc_label, "dst": target_doc_label, "ws": workspace_id},
        )


def set_raw_document_status(
    workspace_id: str,
    doc_label: str,
    status: str,
) -> None:
    """Set the ``status`` property on a :Document node (additive, no index)."""
    driver = get_graph_driver()
    with driver.session() as session:
        session.run(
            """
            MATCH (d:Document {doc_label: $doc_label, workspace_id: $ws})
            SET d.status = $status
            """,
            {"doc_label": doc_label, "ws": workspace_id, "status": status},
        )
```

- [ ] **Step 9: Run all tests + commit.**

Run: `make lint && make typecheck && make test` (three separate commands).

```
git add src/metatron/storage/postgres.py src/metatron/storage/qdrant.py src/metatron/storage/raw_document_graph.py tests/unit/storage/test_raw_documents_lifecycle.py tests/unit/storage/test_qdrant_update_payload.py
git commit -m "feat(MTRNIX-313): storage — raw_document lifecycle, qdrant payload sync, raw_document graph helpers"
```

---

### Task 4: Rename `storage/memory_freshness_pg.py` → `storage/freshness_pg.py` with compat shim; add `target_kind`

**Files:**
- Rename: `src/metatron/storage/memory_freshness_pg.py` → `src/metatron/storage/freshness_pg.py`
- Create (shim): `src/metatron/storage/memory_freshness_pg.py`
- Modify: all importers (grep first — probably 2–4 files in `memory/freshness/`)

- [ ] **Step 1: Grep callers.**

```
grep -rn "memory_freshness_pg\|FreshnessPostgresStore" src/ tests/
```

Record the exact import lines.

- [ ] **Step 2: Rename the file.**

```
git mv src/metatron/storage/memory_freshness_pg.py src/metatron/storage/freshness_pg.py
```

- [ ] **Step 3: Inside `storage/freshness_pg.py`, rename class `FreshnessPostgresStore` → `FreshnessStore`.**

Find-and-replace within the file only. Keep an alias at the bottom:

```python
# Backward compat for Phase A callers (MTRNIX-304).
FreshnessPostgresStore = FreshnessStore
```

- [ ] **Step 4: Add `target_kind` to `save_review_entry` + `find_review_entry`.**

Find `save_review_entry`. Update the INSERT to include `target_kind` column. Update the dataclass-to-row conversion to read `entry.target_kind`. Update `find_review_entry` signature to accept `target_kind: str = "memory_record"` keyword and include `AND target_kind = :target_kind` in the WHERE clause. Update the dataclass-to-row mapping on the read side to populate both `target_id` and `target_kind`.

Update `save_machine_event` — Phase A already has `target_kind`; no change.

- [ ] **Step 5: Create the compat shim at the old path.**

`src/metatron/storage/memory_freshness_pg.py`:

```python
"""Compat shim — the file was renamed to ``freshness_pg.py`` (MTRNIX-313).

Do NOT add new code here. Import from :mod:`metatron.storage.freshness_pg` instead.
"""

from metatron.storage.freshness_pg import (  # noqa: F401
    FreshnessPostgresStore,
    FreshnessStore,
)
```

- [ ] **Step 6: Update Phase A callers that reference the internal table name.**

Inside `freshness_pg.py` the SQL now reads from column `target_id` (not `record_id`). Ensure all SQL has been updated. In Phase A call sites (`memory/freshness/*`), the Python field names stay `record_id` on the dataclass thanks to the alias — no import changes needed.

- [ ] **Step 7: Run tests.**

Run: `make test`
Expected: all Phase A tests still green.

- [ ] **Step 8: Commit.**

```
git add -A
git commit -m "refactor(MTRNIX-313): rename storage.memory_freshness_pg → freshness_pg, add target_kind"
```

---

### Task 5: Promote `freshness/` shared submodule — move coordination, decision_engine, metrics; add targets.py; refactor stages

**Files:**
- Create: `src/metatron/freshness/__init__.py`, `src/metatron/freshness/targets.py`
- Move: `src/metatron/memory/freshness/coordination.py` → `src/metatron/freshness/coordination.py`
- Move: `src/metatron/memory/freshness/decision_engine.py` → `src/metatron/freshness/decision_engine.py`
- Move: `src/metatron/memory/freshness/metrics.py` → `src/metatron/freshness/metrics.py`
- Create: `src/metatron/freshness/apply_decision.py` (extracted)
- Create: `src/metatron/freshness/stages/__init__.py`
- Move+refactor: `src/metatron/memory/freshness/linker.py` → `src/metatron/freshness/stages/linker.py`
- Move+refactor: `src/metatron/memory/freshness/reconciler.py` → `src/metatron/freshness/stages/reconciler.py`
- Move+refactor: `src/metatron/memory/freshness/monitor.py` → `src/metatron/freshness/stages/monitor.py`
- Move+refactor: `src/metatron/memory/freshness/curator.py` → `src/metatron/freshness/stages/curator.py`
- Create (shims): `src/metatron/memory/freshness/{linker,reconciler,monitor,curator,coordination,decision_engine,metrics}.py`

- [ ] **Step 1: Create `src/metatron/freshness/targets.py`.**

```python
"""Target adapter protocol for the freshness pipeline (MTRNIX-313, Phase B).

The pipeline stages are generic over the target kind. Concrete adapters live
elsewhere:

* :mod:`metatron.memory.freshness.target_memory` — ``MemoryTarget`` for agent memory.
* :mod:`metatron.ingestion.freshness.target_raw_document` — ``RawDocumentTarget`` for KB.

The protocol is deliberately *not* in :mod:`metatron.core.interfaces` — that
would force enterprise coordination for every shape tweak. Promote later when
the shape has been stable across a release cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from metatron.core.models import LifecycleStatus


@dataclass
class SimilarityHit:
    """One hit from a target-scoped similarity search."""

    target_id: str
    score: float
    content: str = ""


@dataclass
class FreshnessTargetRecord:
    """Minimal shape the pipeline reads from a target."""

    target_id: str
    workspace_id: str
    content: str
    tags: list[str] = field(default_factory=list)
    status: LifecycleStatus = LifecycleStatus.ACTIVE
    freshness_score: float = 0.5
    superseded_by: str | None = None
    valid_until: datetime | None = None
    updated_at: datetime | None = None
    evidence_count: int = 0
    verification_state: str | None = None
    last_freshness_run_at: datetime | None = None


class FreshnessTarget(Protocol):
    """Adapter binding a pipeline stage to a concrete target store."""

    kind: str  # "memory_record" | "raw_document"
    supports_candidate_promotion: bool  # True for memory, False for KB in Phase B

    async def get(self, workspace_id: str, target_id: str) -> FreshnessTargetRecord | None: ...

    async def update_lifecycle(
        self,
        workspace_id: str,
        target_id: str,
        *,
        status: LifecycleStatus | None = None,
        freshness_score: float | None = None,
        superseded_by: str | None = None,
        evidence_count: int | None = None,
        verification_state: str | None = None,
        valid_until: datetime | None = None,
        last_freshness_run_at: datetime | None = None,
        append_tag: str | None = None,
    ) -> None: ...

    async def similarity_search(
        self,
        workspace_id: str,
        content: str,
        *,
        top_k: int,
    ) -> list[SimilarityHit]: ...

    async def link_edges_batch(
        self,
        workspace_id: str,
        source_id: str,
        edges: list[tuple[str, float]],
    ) -> None:
        """Best-effort. NEVER raises."""

    async def alias_edge(
        self,
        workspace_id: str,
        source_id: str,
        target_id: str,
    ) -> None:
        """Best-effort. NEVER raises."""

    async def sync_downstream_stores(
        self,
        workspace_id: str,
        target_id: str,
        *,
        status: LifecycleStatus,
        freshness_score: float,
    ) -> None:
        """Called after lifecycle status changes. Keeps Qdrant payload and
        Neo4j node properties in sync with PG. Best-effort, NEVER raises.
        """
```

- [ ] **Step 2: Git-move `coordination.py`, `decision_engine.py`, `metrics.py`.**

```
git mv src/metatron/memory/freshness/coordination.py src/metatron/freshness/coordination.py
git mv src/metatron/memory/freshness/decision_engine.py src/metatron/freshness/decision_engine.py
git mv src/metatron/memory/freshness/metrics.py src/metatron/freshness/metrics.py
```

Edit the moved files to update internal relative imports — e.g. if coordination.py referenced `from metatron.memory.freshness...`, replace with `from metatron.freshness...`.

- [ ] **Step 3: Update `coordination.py` lock key builder for `target_kind`.**

Inside `coordination.py`, the lock key builder currently uses `freshness:{stage}:{record_id}`. Change it to:

```python
def _lock_key(stage: str, target_kind: str, target_id: str) -> str:
    # Backward compat: memory call sites don't pass target_kind.
    # Empty prefix keeps the Phase A key shape `freshness:{stage}:{target_id}`.
    if not target_kind or target_kind == "memory_record":
        return f"freshness:{stage}:{target_id}"
    return f"freshness:{stage}:{target_kind}:{target_id}"
```

Update `acquire_lock`, `release`, `heartbeat`, `write_checkpoint`, `read_checkpoint` method signatures to take an optional `target_kind: str = ""` keyword (positional-after-compat); thread through. Phase A callers pass only `stage, target_id` and the default keeps them working.

- [ ] **Step 4: Extract `apply_decision` into `src/metatron/freshness/apply_decision.py`.**

Move the `apply_decision` function from `decision_engine.py` to a new file. Change its signature to take a `FreshnessTarget` instead of a concrete `pg_store`. The function becomes generic — it calls `target.update_lifecycle(...)` for both targets.

- [ ] **Step 5: Create compat shims at `memory/freshness/{coordination,decision_engine,metrics}.py`.**

Each is a one-liner:

```python
# src/metatron/memory/freshness/coordination.py — compat shim (MTRNIX-313)
from metatron.freshness.coordination import *  # noqa: F401, F403
```

- [ ] **Step 6: Move + refactor the four stages.**

```
git mv src/metatron/memory/freshness/linker.py src/metatron/freshness/stages/linker.py
git mv src/metatron/memory/freshness/reconciler.py src/metatron/freshness/stages/reconciler.py
git mv src/metatron/memory/freshness/monitor.py src/metatron/freshness/stages/monitor.py
git mv src/metatron/memory/freshness/curator.py src/metatron/freshness/stages/curator.py
```

For each stage:

1. Change the constructor to take `target: FreshnessTarget` (and remove `pg_store`, `qdrant_store_factory`, `freshness_pg` fields — the adapter owns those concerns).
2. Change `run(workspace_id, record_id)` → `run(workspace_id, target_id)`.
3. Replace `self._pg.get(workspace_id, record_id)` → `self._target.get(workspace_id, target_id)`. Same for `update_lifecycle` → `self._target.update_lifecycle(...)`.
4. Replace the Qdrant factory + `hits = await qdrant.search(...)` chain with `hits = await self._target.similarity_search(workspace_id, record.content, top_k=self._top_k)`.
5. Replace `asyncio.to_thread(link_memory_items_batch, ...)` with `await self._target.link_edges_batch(...)`.
6. Replace `asyncio.to_thread(alias_link_memory_items, ...)` with `await self._target.alias_edge(...)`.
7. Replace writes to `FreshnessPostgresStore` (MachineEvents, ReviewEntries) with a new constructor kwarg `freshness_store: FreshnessStore` that the worker wires in.
8. **Monitor only:** add the age-gate. After fetching `record`, skip the rule-based demotion if `record.last_freshness_run_at is None AND the stale rule would trigger` — in that case, *only* write `last_freshness_run_at=now` via `update_lifecycle` and return `None`. Subsequent runs apply the rules normally. Rationale: avoids a bulk STALE avalanche on day one. This applies to both targets but is the mitigation for KB primarily.
9. **Curator only:** short-circuit when `target.supports_candidate_promotion is False`. Return `None` without acquiring a lock.
10. **Monitor only:** after `update_lifecycle`, call `await self._target.sync_downstream_stores(workspace_id, target_id, status=new_status, freshness_score=new_score)`. This hook is how KB Qdrant payloads get updated.

Reconciler: the `ReviewEntry` creation uses `target_id=target_id, target_kind=self._target.kind`. The `find_review_entry` call carries `target_kind` too.

- [ ] **Step 7: Create compat shims at `memory/freshness/{linker,reconciler,monitor,curator}.py`.**

Each is a one-liner `from metatron.freshness.stages.linker import *`.

- [ ] **Step 8: Update `src/metatron/freshness/__init__.py` + `stages/__init__.py`.**

Re-export the public surface: `CoordinationStore`, `FreshnessTarget`, `SimilarityHit`, `FreshnessTargetRecord`, `DecisionEngine`, `RuleBasedDecisionEngine`, `LLMBackedDecisionEngine`, `build_default_decision_engine`, `apply_decision`, `Linker`, `Reconciler`, `FreshnessMonitor`, `Curator`, `metrics`.

- [ ] **Step 9: Run tests — regression guard.**

Run: `make lint && make typecheck && make test`
Expected: all Phase A memory-freshness tests pass. If any break, the refactor went too far. Fix before committing.

- [ ] **Step 10: Commit.**

```
git add -A
git commit -m "refactor(MTRNIX-313): promote shared freshness submodule, stages take FreshnessTarget adapter"
```

**Acceptance:** Phase A memory-freshness tests remain green. Stage classes now take an adapter. Memory re-export shims preserve existing import paths.

---

### Task 6: `MemoryTarget` adapter — wrap Phase A stores to implement `FreshnessTarget`

**Files:**
- Create: `src/metatron/memory/freshness/target_memory.py`
- Create: `tests/unit/memory/freshness/test_target_memory.py`

- [ ] **Step 1: TDD — write adapter tests.**

`tests/unit/memory/freshness/test_target_memory.py`:

```python
"""MemoryTarget adapter conformance tests (MTRNIX-313)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.models import LifecycleStatus, MemoryRecord
from metatron.memory.freshness.target_memory import MemoryTarget

pytestmark = pytest.mark.asyncio


async def test_memory_target_kind_and_supports_promotion() -> None:
    pg = MagicMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda ws: MagicMock())
    assert target.kind == "memory_record"
    assert target.supports_candidate_promotion is True


async def test_get_returns_freshness_target_record() -> None:
    pg = MagicMock()
    pg.get = AsyncMock(return_value=MemoryRecord(
        id="r1", workspace_id="ws", content="hello",
    ))
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda ws: MagicMock())
    rec = await target.get("ws", "r1")
    assert rec is not None
    assert rec.target_id == "r1"
    assert rec.content == "hello"


async def test_update_lifecycle_maps_to_pg_update_lifecycle() -> None:
    pg = MagicMock()
    pg.update_lifecycle = AsyncMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda ws: MagicMock())
    await target.update_lifecycle("ws", "r1", status=LifecycleStatus.STALE)
    pg.update_lifecycle.assert_awaited_once()
    kwargs = pg.update_lifecycle.await_args.kwargs
    assert kwargs["status"] is LifecycleStatus.STALE


async def test_link_edges_batch_is_best_effort() -> None:
    pg = MagicMock()
    qdrant = MagicMock()
    target = MemoryTarget(pg_store=pg, qdrant_store_factory=lambda ws: qdrant)
    # Should not raise even if Neo4j is unavailable.
    await target.link_edges_batch("ws", "r1", [("r2", 0.9)])
```

Run: `pytest tests/unit/memory/freshness/test_target_memory.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement `MemoryTarget`.**

```python
"""MemoryTarget adapter — wraps MemoryPostgresStore + MemoryQdrantStore for the
generic freshness pipeline (MTRNIX-313).

This adapter is what makes the Phase A freshness stages work unchanged: it
translates the generic ``FreshnessTarget`` calls into the concrete memory store
operations that Phase A used directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import LifecycleStatus
from metatron.freshness.targets import (
    FreshnessTargetRecord,
    SimilarityHit,
)

if TYPE_CHECKING:
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore

logger = structlog.get_logger()


class MemoryTarget:
    kind = "memory_record"
    supports_candidate_promotion = True

    def __init__(
        self,
        *,
        pg_store: MemoryPostgresStore,
        qdrant_store_factory: Callable[[str], MemoryQdrantStore],
    ) -> None:
        self._pg = pg_store
        self._qdrant_factory = qdrant_store_factory

    async def get(self, workspace_id: str, target_id: str) -> FreshnessTargetRecord | None:
        rec = await self._pg.get(workspace_id, target_id)
        if rec is None:
            return None
        return FreshnessTargetRecord(
            target_id=rec.id,
            workspace_id=rec.workspace_id,
            content=rec.content,
            tags=list(rec.tags),
            status=rec.status,
            freshness_score=rec.freshness_score,
            superseded_by=rec.superseded_by,
            valid_until=rec.valid_until,
            updated_at=rec.updated_at,
            evidence_count=rec.evidence_count,
            verification_state=rec.verification_state,
            last_freshness_run_at=getattr(rec, "last_freshness_run_at", None),
        )

    async def update_lifecycle(
        self,
        workspace_id: str,
        target_id: str,
        *,
        status: LifecycleStatus | None = None,
        freshness_score: float | None = None,
        superseded_by: str | None = None,
        evidence_count: int | None = None,
        verification_state: str | None = None,
        valid_until: datetime | None = None,
        last_freshness_run_at: datetime | None = None,
        append_tag: str | None = None,
    ) -> None:
        kwargs: dict[str, object] = {}
        if status is not None:
            kwargs["status"] = status
        if freshness_score is not None:
            kwargs["freshness_score"] = freshness_score
        if superseded_by is not None:
            kwargs["superseded_by"] = superseded_by
        if evidence_count is not None:
            kwargs["evidence_count"] = evidence_count
        if verification_state is not None:
            kwargs["verification_state"] = verification_state
        if valid_until is not None:
            kwargs["valid_until"] = valid_until
        if append_tag is not None:
            kwargs["append_tag"] = append_tag
        # last_freshness_run_at is not persisted on memory_records in Phase A;
        # field is present on FreshnessTargetRecord for symmetry but ignored
        # on write for memory target (KB target stores it).
        await self._pg.update_lifecycle(workspace_id, target_id, **kwargs)

    async def similarity_search(
        self, workspace_id: str, content: str, *, top_k: int,
    ) -> list[SimilarityHit]:
        qdrant = self._qdrant_factory(workspace_id)
        hits = await qdrant.search(content, top_k=top_k)
        return [
            SimilarityHit(
                target_id=str(h.get("record_id") or ""),
                score=float(h.get("score") or 0.0),
                content=str(h.get("content") or ""),
            )
            for h in hits
            if h.get("record_id")
        ]

    async def link_edges_batch(
        self, workspace_id: str, source_id: str, edges: list[tuple[str, float]],
    ) -> None:
        from metatron.storage.memory_graph import link_memory_items_batch

        batch = [(source_id, dst, score) for dst, score in edges]
        try:
            await asyncio.to_thread(link_memory_items_batch, workspace_id, batch)
        except Exception:
            logger.warning(
                "freshness.memory_target.link_edges_failed",
                workspace_id=workspace_id,
                source_id=source_id,
                edge_count=len(edges),
                exc_info=True,
            )

    async def alias_edge(
        self, workspace_id: str, source_id: str, target_id: str,
    ) -> None:
        from metatron.memory.freshness.reconciler import alias_link_memory_items  # compat shim

        try:
            await asyncio.to_thread(alias_link_memory_items, workspace_id, source_id, target_id)
        except Exception:
            logger.warning(
                "freshness.memory_target.alias_failed",
                workspace_id=workspace_id,
                source_id=source_id,
                target_id=target_id,
                exc_info=True,
            )

    async def sync_downstream_stores(
        self, workspace_id: str, target_id: str, *, status: LifecycleStatus, freshness_score: float,
    ) -> None:
        # Memory does not mirror status on Qdrant chunk payloads in Phase B.
        # Neo4j MemoryRecord already gets updated via PG writes elsewhere.
        # This is a no-op today; kept for interface symmetry.
        return None
```

- [ ] **Step 3: Run tests.**

Run: `pytest tests/unit/memory/freshness/test_target_memory.py -v`
Expected: PASS.

- [ ] **Step 4: Run the full Phase A test suite.**

Run: `make test`
Expected: all green.

- [ ] **Step 5: Commit.**

```
git add src/metatron/memory/freshness/target_memory.py tests/unit/memory/freshness/test_target_memory.py
git commit -m "feat(MTRNIX-313): MemoryTarget adapter for generic freshness stages"
```

---

### Task 7: Regression guard — rewire Phase A worker to use `MemoryTarget` + generic stages

**Files:**
- Modify: `src/metatron/memory/freshness/worker.py`

- [ ] **Step 1: Update `_build_worker` in `worker.py`.**

Replace the direct instantiation of `Linker(pg_store=..., qdrant_store_factory=..., freshness_pg=..., coordination=..., ...)` with:

```python
from metatron.freshness.stages.linker import Linker
from metatron.freshness.stages.reconciler import Reconciler
from metatron.freshness.stages.monitor import FreshnessMonitor
from metatron.freshness.stages.curator import Curator
from metatron.memory.freshness.target_memory import MemoryTarget

memory_target = MemoryTarget(
    pg_store=pg_store,
    qdrant_store_factory=qdrant_factory,
)

linker = Linker(target=memory_target, freshness_store=freshness_pg, coordination=coordination,
                threshold=settings.freshness_linker_threshold, lock_ttl=settings.freshness_lock_ttl_seconds)
reconciler = Reconciler(target=memory_target, freshness_store=freshness_pg, coordination=coordination,
                        threshold=settings.freshness_reconciler_threshold, lock_ttl=settings.freshness_lock_ttl_seconds)
monitor = FreshnessMonitor(target=memory_target, freshness_store=freshness_pg, coordination=coordination,
                           stale_after_days=settings.freshness_stale_after_days, lock_ttl=settings.freshness_lock_ttl_seconds)
curator = Curator(target=memory_target, freshness_store=freshness_pg, coordination=coordination,
                  lock_ttl=settings.freshness_lock_ttl_seconds)
```

The `FreshnessWorker` constructor keeps the same signature externally (stages are still passed in), but now holds adapter-based stages. `_process_job` stays unchanged — in Task 10 we'll add the `target_kind` switch.

- [ ] **Step 2: Run Phase A freshness tests.**

```
pytest tests/unit/memory/freshness/ tests/integration/memory/freshness/ -v
```
Expected: all green.

- [ ] **Step 3: Run full test suite.**

Run: `make lint && make typecheck && make test`
Expected: all green.

- [ ] **Step 4: Commit.**

```
git add src/metatron/memory/freshness/worker.py
git commit -m "refactor(MTRNIX-313): wire memory worker via MemoryTarget adapter (regression guard)"
```

**Acceptance:** Phase A tests green; memory freshness behaviour unchanged.

---

### Task 8: `RawDocumentTarget` adapter

**Files:**
- Create: `src/metatron/ingestion/freshness/__init__.py`
- Create: `src/metatron/ingestion/freshness/target_raw_document.py`
- Create: `tests/unit/ingestion/freshness/__init__.py`
- Create: `tests/unit/ingestion/freshness/test_target_raw_document.py`

- [ ] **Step 1: TDD — adapter tests.**

`tests/unit/ingestion/freshness/test_target_raw_document.py`:

```python
"""RawDocumentTarget adapter tests (MTRNIX-313)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.models import LifecycleStatus, RawDocument
from metatron.ingestion.freshness.target_raw_document import RawDocumentTarget

pytestmark = pytest.mark.asyncio


async def test_target_identity() -> None:
    t = RawDocumentTarget(pg_store=MagicMock(), qdrant_factory=MagicMock())
    assert t.kind == "raw_document"
    assert t.supports_candidate_promotion is False


async def test_get_returns_freshness_target_record() -> None:
    pg = MagicMock()
    pg.get_raw_document_by_id = AsyncMock(return_value=RawDocument(
        id="doc-1", workspace_id="ws", title="t", content="body",
        status=LifecycleStatus.ACTIVE,
    ))
    t = RawDocumentTarget(pg_store=pg, qdrant_factory=MagicMock())
    rec = await t.get("ws", "doc-1")
    assert rec is not None
    assert rec.target_id == "doc-1"
    assert rec.content == "body"


async def test_similarity_search_dedups_by_doc_label() -> None:
    pg = MagicMock()
    qdrant = MagicMock()
    qdrant.hybrid_search = AsyncMock(return_value=[
        {"doc_label": "doc-2", "score": 0.9, "content": "c1"},
        {"doc_label": "doc-2", "score": 0.8, "content": "c2"},  # dedup: same doc
        {"doc_label": "doc-3", "score": 0.7, "content": "c3"},
    ])
    t = RawDocumentTarget(pg_store=pg, qdrant_factory=lambda ws: qdrant)
    hits = await t.similarity_search("ws", "query", top_k=10)
    assert [h.target_id for h in hits] == ["doc-2", "doc-3"]


async def test_sync_downstream_stores_writes_qdrant_payload() -> None:
    qdrant = MagicMock()
    qdrant.update_payload_by_doc_label = AsyncMock()
    t = RawDocumentTarget(pg_store=MagicMock(), qdrant_factory=lambda ws: qdrant)
    await t.sync_downstream_stores(
        "ws", "doc-1", status=LifecycleStatus.ARCHIVED, freshness_score=0.0,
    )
    qdrant.update_payload_by_doc_label.assert_awaited_once_with(
        workspace_id="ws",
        doc_label="doc-1",
        payload={"status": "archived", "freshness_score": 0.0},
    )
```

Run: `pytest tests/unit/ingestion/freshness/test_target_raw_document.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement `RawDocumentTarget`.**

```python
"""RawDocumentTarget adapter — KB raw_documents plugged into the freshness pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

import structlog

from metatron.core.models import LifecycleStatus
from metatron.freshness.targets import (
    FreshnessTargetRecord,
    SimilarityHit,
)

if TYPE_CHECKING:
    from metatron.storage.postgres import PostgresStore
    from metatron.storage.qdrant import AsyncQdrantVectorStore

logger = structlog.get_logger()


class RawDocumentTarget:
    kind = "raw_document"
    supports_candidate_promotion = False  # Phase B: no CANDIDATE state for KB

    def __init__(
        self,
        *,
        pg_store: PostgresStore,
        qdrant_factory: Callable[[str], AsyncQdrantVectorStore],
    ) -> None:
        self._pg = pg_store
        self._qdrant_factory = qdrant_factory

    async def get(self, workspace_id: str, target_id: str) -> FreshnessTargetRecord | None:
        doc = await self._pg.get_raw_document_by_id(workspace_id, target_id)
        if doc is None:
            return None
        updated = doc.source_updated_at or doc.updated_at
        return FreshnessTargetRecord(
            target_id=doc.id,
            workspace_id=doc.workspace_id,
            content=doc.content,
            tags=[],  # KB has no first-class tags list; could derive from metadata later
            status=doc.status,
            freshness_score=doc.freshness_score,
            superseded_by=doc.superseded_by,
            valid_until=doc.valid_until,
            updated_at=updated,
            evidence_count=doc.evidence_count,
            verification_state=doc.verification_state,
            last_freshness_run_at=doc.last_freshness_run_at,
        )

    async def update_lifecycle(
        self,
        workspace_id: str,
        target_id: str,
        *,
        status: LifecycleStatus | None = None,
        freshness_score: float | None = None,
        superseded_by: str | None = None,
        evidence_count: int | None = None,
        verification_state: str | None = None,
        valid_until: datetime | None = None,
        last_freshness_run_at: datetime | None = None,
        append_tag: str | None = None,
    ) -> None:
        # KB has no tags column to append to in Phase B; ignore ``append_tag``.
        await self._pg.update_raw_document_lifecycle(
            workspace_id,
            target_id,
            status=status,
            freshness_score=freshness_score,
            superseded_by=superseded_by,
            evidence_count=evidence_count,
            verification_state=verification_state,
            valid_until=valid_until,
            last_freshness_run_at=last_freshness_run_at,
        )

    async def similarity_search(
        self, workspace_id: str, content: str, *, top_k: int,
    ) -> list[SimilarityHit]:
        qdrant = self._qdrant_factory(workspace_id)
        hits = await qdrant.hybrid_search(content, limit=top_k)
        seen: set[str] = set()
        out: list[SimilarityHit] = []
        for h in hits:
            payload = h.get("payload", h)
            doc_label = str(payload.get("doc_label") or "")
            if not doc_label or doc_label in seen:
                continue
            seen.add(doc_label)
            out.append(SimilarityHit(
                target_id=doc_label,
                score=float(h.get("score") or 0.0),
                content=str(payload.get("content") or payload.get("text") or ""),
            ))
        return out

    async def link_edges_batch(
        self, workspace_id: str, source_id: str, edges: list[tuple[str, float]],
    ) -> None:
        if not edges:
            return
        from metatron.storage.raw_document_graph import link_raw_documents_batch

        batch = [(source_id, dst, score) for dst, score in edges]
        try:
            await asyncio.to_thread(link_raw_documents_batch, workspace_id, batch)
        except Exception:
            logger.warning(
                "freshness.raw_document_target.link_edges_failed",
                workspace_id=workspace_id,
                source_id=source_id,
                edge_count=len(edges),
                exc_info=True,
            )

    async def alias_edge(
        self, workspace_id: str, source_id: str, target_id: str,
    ) -> None:
        from metatron.storage.raw_document_graph import alias_raw_documents

        try:
            await asyncio.to_thread(alias_raw_documents, workspace_id, source_id, target_id)
        except Exception:
            logger.warning(
                "freshness.raw_document_target.alias_failed",
                workspace_id=workspace_id,
                source_id=source_id,
                target_id=target_id,
                exc_info=True,
            )

    async def sync_downstream_stores(
        self, workspace_id: str, target_id: str, *, status: LifecycleStatus, freshness_score: float,
    ) -> None:
        qdrant = self._qdrant_factory(workspace_id)
        try:
            await qdrant.update_payload_by_doc_label(
                workspace_id=workspace_id,
                doc_label=target_id,
                payload={"status": status.value, "freshness_score": freshness_score},
            )
        except Exception:
            logger.warning(
                "freshness.raw_document_target.qdrant_payload_sync_failed",
                workspace_id=workspace_id,
                target_id=target_id,
                exc_info=True,
            )
        # Neo4j best-effort property write.
        try:
            from metatron.storage.raw_document_graph import set_raw_document_status

            await asyncio.to_thread(set_raw_document_status, workspace_id, target_id, status.value)
        except Exception:
            logger.debug(
                "freshness.raw_document_target.neo4j_status_skipped",
                workspace_id=workspace_id,
                target_id=target_id,
                exc_info=True,
            )
```

- [ ] **Step 3: Run tests.**

Run: `pytest tests/unit/ingestion/freshness/test_target_raw_document.py -v`
Expected: PASS.

- [ ] **Step 4: Commit.**

```
git add src/metatron/ingestion/freshness/__init__.py src/metatron/ingestion/freshness/target_raw_document.py tests/unit/ingestion/freshness/
git commit -m "feat(MTRNIX-313): RawDocumentTarget adapter for KB freshness pipeline"
```

---

### Task 9: KB producer hook + connector sync wire-up

**Files:**
- Create: `src/metatron/ingestion/freshness/producer.py`
- Create: `tests/unit/ingestion/freshness/test_producer_raw_document.py`
- Modify: `src/metatron/api/routes/connections.py`

- [ ] **Step 1: TDD producer tests.**

`tests/unit/ingestion/freshness/test_producer_raw_document.py`:

```python
"""enqueue_raw_document_if_enabled — flag-off, flag-on, fail-soft (MTRNIX-313)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatron.ingestion.freshness.producer import enqueue_raw_document_if_enabled

pytestmark = pytest.mark.asyncio


async def test_noop_when_master_flag_off(monkeypatch) -> None:
    settings = MagicMock(freshness_enabled=False, freshness_kb_enabled=True)
    coord = MagicMock()
    coord.enqueue_job = AsyncMock()
    with patch("metatron.ingestion.freshness.producer.get_settings", return_value=settings):
        await enqueue_raw_document_if_enabled("ws", "doc-1", "knowledge_changed", coordination=coord)
    coord.enqueue_job.assert_not_awaited()


async def test_noop_when_kb_flag_off(monkeypatch) -> None:
    settings = MagicMock(freshness_enabled=True, freshness_kb_enabled=False)
    coord = MagicMock()
    coord.enqueue_job = AsyncMock()
    with patch("metatron.ingestion.freshness.producer.get_settings", return_value=settings):
        await enqueue_raw_document_if_enabled("ws", "doc-1", "knowledge_changed", coordination=coord)
    coord.enqueue_job.assert_not_awaited()


async def test_enqueues_job_with_target_kind_raw_document() -> None:
    settings = MagicMock(freshness_enabled=True, freshness_kb_enabled=True)
    coord = MagicMock()
    coord.enqueue_job = AsyncMock()
    with patch("metatron.ingestion.freshness.producer.get_settings", return_value=settings):
        await enqueue_raw_document_if_enabled("ws", "doc-1", "content_changed", coordination=coord)
    coord.enqueue_job.assert_awaited_once()
    job = coord.enqueue_job.await_args.args[0]
    assert job.workspace_id == "ws"
    assert job.target_kind == "raw_document"
    assert job.target_id == "doc-1"
    assert job.event_type == "content_changed"


async def test_swallows_redis_errors() -> None:
    settings = MagicMock(freshness_enabled=True, freshness_kb_enabled=True)
    coord = MagicMock()
    coord.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))
    with patch("metatron.ingestion.freshness.producer.get_settings", return_value=settings):
        # Must not raise — producer is fail-soft.
        await enqueue_raw_document_if_enabled("ws", "doc-1", "knowledge_changed", coordination=coord)
```

Run: `pytest tests/unit/ingestion/freshness/test_producer_raw_document.py -v`
Expected: FAIL.

- [ ] **Step 2: Implement producer.**

```python
"""KB producer hook — enqueue freshness jobs after raw_documents writes (MTRNIX-313)."""

from __future__ import annotations

import structlog

from metatron.core.config import get_settings
from metatron.core.models import FreshnessJob
from metatron.freshness.coordination import CoordinationStore

logger = structlog.get_logger()

_default_store: CoordinationStore | None = None


def _build_default_coordination() -> CoordinationStore:
    global _default_store  # noqa: PLW0603
    if _default_store is None:
        from metatron.storage.redis import RedisStore

        settings = get_settings()
        _default_store = CoordinationStore(redis=RedisStore(settings.redis_url))
    return _default_store


def _reset_default_for_tests() -> None:
    global _default_store  # noqa: PLW0603
    _default_store = None


async def enqueue_raw_document_if_enabled(
    workspace_id: str,
    raw_document_id: str,
    event_type: str = "knowledge_changed",
    *,
    coordination: CoordinationStore | None = None,
    payload: dict[str, str] | None = None,
) -> None:
    """Enqueue a freshness job for a raw_document when both flags are on.

    Args:
        workspace_id: Tenant id.
        raw_document_id: ``raw_documents.id`` (PK).
        event_type: One of ``knowledge_changed`` (new row), ``content_changed``
            (update of existing row), ``knowledge_deleted``, ``scheduled_scan``.
    """
    settings = get_settings()
    if not settings.freshness_enabled or not settings.freshness_kb_enabled:
        return
    if not workspace_id or not raw_document_id:
        return
    try:
        store = coordination or _build_default_coordination()
        job = FreshnessJob(
            workspace_id=workspace_id,
            event_type=event_type,
            target_kind="raw_document",
            target_id=raw_document_id,
            payload=dict(payload or {}),
        )
        await store.enqueue_job(job)
    except Exception:
        logger.warning(
            "freshness.raw_document_producer.enqueue_failed",
            workspace_id=workspace_id,
            raw_document_id=raw_document_id,
            event_type=event_type,
            exc_info=True,
        )
```

- [ ] **Step 3: Run tests.**

Run: `pytest tests/unit/ingestion/freshness/test_producer_raw_document.py -v`
Expected: PASS.

- [ ] **Step 4: Wire into `api/routes/connections.py::_run_connection_sync`.**

Find the block after `upsert_result = await store.upsert_raw_documents(...)` and before Phase 2 (Qdrant ingest). Add:

```python
# Phase 1b: Enqueue KB freshness jobs (flag-gated).
# Flag-off: producer is a no-op — zero Redis traffic.
if upsert_result and upsert_result.get("changed_source_ids"):
    from metatron.ingestion.freshness.producer import enqueue_raw_document_if_enabled

    for src_id in upsert_result["changed_source_ids"]:
        raw_doc = await store.get_raw_document(
            workspace_id=workspace_id,
            connector_type=connector_type,
            source_id=src_id,
        )
        if raw_doc is None:
            continue
        # New rows come through as "knowledge_changed"; already-present rows
        # with content change come through as "content_changed". The upsert
        # result doesn't distinguish today — both are in ``changed_source_ids``.
        # Phase B uses "content_changed" as the generic label; the worker
        # doesn't branch on event_type for KB yet.
        await enqueue_raw_document_if_enabled(
            workspace_id=workspace_id,
            raw_document_id=raw_doc.id,
            event_type="content_changed",
        )
```

Note on `get_raw_document` vs `get_raw_document_by_id` — the former takes `(workspace_id, connector_type, source_id)` and returns the row; the latter takes `(workspace_id, id)` — use the former here because we have `source_id` in `changed_source_ids`.

- [ ] **Step 5: Run the lint/typecheck/test trio.**

Run: `make lint && make typecheck && make test`
Expected: all green.

- [ ] **Step 6: Commit.**

```
git add src/metatron/ingestion/freshness/producer.py src/metatron/api/routes/connections.py tests/unit/ingestion/freshness/test_producer_raw_document.py
git commit -m "feat(MTRNIX-313): KB producer hook wired into connector sync, flag-gated"
```

---

### Task 10: Worker routing — dispatch jobs by `target_kind`, build both pipelines

**Files:**
- Modify: `src/metatron/memory/freshness/worker.py`

- [ ] **Step 1: Refactor `_build_worker` to build both pipelines.**

Inside `_build_worker`, after constructing `memory_target`, also construct:

```python
from metatron.ingestion.freshness.target_raw_document import RawDocumentTarget
from metatron.storage.postgres import PostgresStore
from metatron.storage.qdrant import get_async_hybrid_store

pg_postgres = PostgresStore(settings.postgres_dsn)
_kb_qdrant_cache: dict[str, AsyncQdrantVectorStore] = {}

async def _kb_qdrant_factory(ws: str):
    if ws not in _kb_qdrant_cache:
        _kb_qdrant_cache[ws] = await get_async_hybrid_store(ws)
    return _kb_qdrant_cache[ws]

raw_doc_target = RawDocumentTarget(
    pg_store=pg_postgres,
    qdrant_factory=_kb_qdrant_factory,  # NOTE: factory returns an awaitable — adjust adapter or factory
)
```

**Gotcha:** `get_async_hybrid_store` is an async factory; the `RawDocumentTarget.qdrant_factory` signature expects a sync callable. Resolution: change the adapter's `qdrant_factory` signature to `Callable[[str], Awaitable[AsyncQdrantVectorStore]]` and `await` the call at use sites. Update Task 8 adapter tests accordingly (the existing mock-based tests work either way if the mock factory returns an awaitable; update them to use `AsyncMock` or a wrapped coroutine).

(This is why the design section mentioned the factory nuance; the plan handles it here rather than in Task 8, where the focus was the adapter's surface.)

Also construct KB-stage instances, identical to memory but using the KB target and `freshness_kb_stale_after_days`:

```python
kb_linker = Linker(target=raw_doc_target, freshness_store=freshness_pg,
                   coordination=coordination,
                   threshold=settings.freshness_linker_threshold,
                   lock_ttl=settings.freshness_lock_ttl_seconds)
kb_reconciler = Reconciler(target=raw_doc_target, freshness_store=freshness_pg,
                           coordination=coordination,
                           threshold=settings.freshness_reconciler_threshold,
                           lock_ttl=settings.freshness_lock_ttl_seconds)
kb_monitor = FreshnessMonitor(target=raw_doc_target, freshness_store=freshness_pg,
                              coordination=coordination,
                              stale_after_days=settings.freshness_kb_stale_after_days,
                              lock_ttl=settings.freshness_lock_ttl_seconds)
kb_curator = Curator(target=raw_doc_target, freshness_store=freshness_pg,
                     coordination=coordination,
                     lock_ttl=settings.freshness_lock_ttl_seconds)
```

- [ ] **Step 2: Add a pipeline-dispatch struct.**

```python
@dataclass
class _Pipeline:
    linker: Linker
    reconciler: Reconciler
    monitor: FreshnessMonitor
    curator: Curator
    target: FreshnessTarget

pipelines: dict[str, _Pipeline] = {
    "memory_record": _Pipeline(linker, reconciler, monitor, curator, memory_target),
    "raw_document": _Pipeline(kb_linker, kb_reconciler, kb_monitor, kb_curator, raw_doc_target),
}
```

Pass `pipelines` into `FreshnessWorker(..., pipelines=pipelines)`. The existing stage fields on `FreshnessWorker` (`linker`, `reconciler`, ...) are deprecated; switch `_process_job` to look up the pipeline by `job.target_kind`:

```python
pipeline = self._pipelines.get(job.target_kind)
if pipeline is None:
    logger.warning("freshness.worker.unknown_target_kind", target_kind=job.target_kind)
    return
await pipeline.linker.run(ws, record_id)
await pipeline.reconciler.run(ws, record_id)
await pipeline.monitor.run(ws, record_id)
await pipeline.curator.run(ws, record_id)
...
record = await pipeline.target.get(ws, record_id)
...
result = await apply_decision(
    workspace_id=ws, record=record, decision=decision,
    threshold=settings.freshness_decision_confidence_threshold,
    target=pipeline.target, freshness_store=self._freshness_pg,
)
```

The `apply_decision` function's signature changes (Task 5 already extracted it to take a target rather than a pg_store — make sure this is reflected).

- [ ] **Step 3: Update worker constructor + `_process_job`.**

Keep the old per-stage kwargs on the constructor for backward compat with the Phase A test suite, but treat them as an implicit memory pipeline; if `pipelines` is passed, use it. That's the simplest migration path for the existing tests.

Actually, cleanest: update Phase A tests to use the `pipelines` kwarg. Tests that explicitly constructed `FreshnessWorker` with `linker=`, `reconciler=`, etc. get updated to:

```python
pipelines = {"memory_record": _Pipeline(linker, reconciler, monitor, curator, memory_target)}
worker = FreshnessWorker(..., pipelines=pipelines)
```

- [ ] **Step 4: Write a new worker test covering the dispatch.**

`tests/unit/memory/freshness/test_worker_target_kind_dispatch.py`:

```python
"""Worker dispatches jobs by target_kind (MTRNIX-313)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from metatron.core.models import FreshnessJob
from metatron.memory.freshness.worker import FreshnessWorker, _Pipeline

pytestmark = pytest.mark.asyncio


async def test_unknown_target_kind_is_skipped(monkeypatch) -> None:
    coord = MagicMock()
    coord.list_active_workspaces = AsyncMock(return_value=["ws"])
    coord.queue_depth = AsyncMock(return_value=1)
    coord.dequeue_batch = AsyncMock(return_value=[
        FreshnessJob(workspace_id="ws", target_kind="alien", target_id="x"),
    ])
    worker = FreshnessWorker(
        coordination=coord,
        freshness_pg=MagicMock(save_machine_event=AsyncMock()),
        decision_engine=MagicMock(),
        pipelines={},
    )
    processed = await worker.run_once(max_jobs=10)
    # Unknown target_kind should still count as processed (so the queue drains)
    # but no stage runs. Verify machine event shows skip reason.
    assert processed == 1
```

Run: `pytest tests/unit/memory/freshness/test_worker_target_kind_dispatch.py -v`
Expected: PASS after implementation.

- [ ] **Step 5: Run full Phase A + new tests.**

```
pytest tests/unit/memory/freshness/ tests/unit/freshness/ tests/integration/memory/freshness/ -v
```
Expected: all green.

- [ ] **Step 6: Commit.**

```
git add src/metatron/memory/freshness/worker.py tests/unit/memory/freshness/test_worker_target_kind_dispatch.py
git commit -m "feat(MTRNIX-313): worker dispatches jobs by target_kind, builds both pipelines"
```

---

### Task 11: Retrieval filter pushdown (behind `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED`)

**Files:**
- Modify: `src/metatron/retrieval/search.py`
- Modify: `src/metatron/retrieval/channels.py`
- Create: `tests/unit/retrieval/test_freshness_filter.py`

- [ ] **Step 1: TDD — filter-construction test.**

```python
"""Freshness filter pushdown (MTRNIX-313)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_build_freshness_filter_none_when_flag_off() -> None:
    from metatron.retrieval.search import _build_freshness_filter

    settings = MagicMock(freshness_kb_search_filter_enabled=False)
    assert _build_freshness_filter(settings) is None


def test_build_freshness_filter_excludes_archived_when_flag_on() -> None:
    from metatron.retrieval.search import _build_freshness_filter

    settings = MagicMock(freshness_kb_search_filter_enabled=True)
    flt = _build_freshness_filter(settings)
    assert flt is not None
    # Filter should use a must_not on status=archived, or equivalent shape.
    # Assert shape loosely since Qdrant's Python client version may differ.
```

Run — expect `ImportError`.

- [ ] **Step 2: Add `_build_freshness_filter` helper in `retrieval/search.py`.**

```python
def _build_freshness_filter(settings: Settings):
    """Build a Qdrant Filter to exclude ARCHIVED/SUPERSEDED docs.

    Returns None when the KB search filter flag is off — callers must
    treat None as "apply no freshness filter".
    """
    if not settings.freshness_kb_search_filter_enabled:
        return None
    try:
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        return Filter(
            must_not=[
                FieldCondition(key="status", match=MatchValue(value="archived")),
                FieldCondition(key="status", match=MatchValue(value="superseded")),
            ],
        )
    except Exception:
        return None
```

- [ ] **Step 3: Thread through `RecallContext` and channels.**

In `channels.py`, add `freshness_filter: Filter | None = None` to `RecallContext`. In each channel's Qdrant call, if both `access_filter` and `freshness_filter` are non-None, combine them:

```python
def _combine_filters(access_filter, freshness_filter):
    if access_filter is None:
        return freshness_filter
    if freshness_filter is None:
        return access_filter
    from qdrant_client.http.models import Filter

    combined_must = list(access_filter.must or []) + list(freshness_filter.must or [])
    combined_must_not = list(access_filter.must_not or []) + list(freshness_filter.must_not or [])
    combined_should = list(access_filter.should or []) + list(freshness_filter.should or [])
    return Filter(must=combined_must, must_not=combined_must_not, should=combined_should)
```

Call `_combine_filters` wherever `ctx.access_filter` is passed to Qdrant.

- [ ] **Step 4: Add `exclude_archived` to PG metadata channel.**

In `recall_metadata_async`, add an `exclude_archived: bool` arg defaulting to `settings.freshness_kb_search_filter_enabled`. Thread into `store.search_by_status` / `store.search_by_assignee` / etc. Add the kwarg to those storage functions (query gets `AND status != 'archived'`).

- [ ] **Step 5: Post-filter `recall_graph_async` results by PG status.**

After the Neo4j traversal returns `doc_labels`, batch-fetch `raw_documents.status` for the workspace's `doc_labels`:

```python
async def _filter_doc_labels_by_status(pg_store, workspace_id, doc_labels):
    if not doc_labels:
        return doc_labels
    async with pg_store._engine.begin() as conn:
        result = await conn.execute(
            text("""
                SELECT id FROM raw_documents
                WHERE workspace_id = :ws AND id = ANY(:ids)
                  AND status NOT IN ('archived', 'superseded')
            """),
            {"ws": workspace_id, "ids": list(doc_labels)},
        )
        allowed = {row._mapping["id"] for row in result}
    return [label for label in doc_labels if label in allowed]
```

Only call when `settings.freshness_kb_search_filter_enabled is True`.

- [ ] **Step 6: Pass `freshness_filter` to `RecallContext` construction in `search.py`.**

Inside `_run_recall_channels_async` or its builder, call `_build_freshness_filter(settings)` and set on the context.

- [ ] **Step 7: Run tests + commit.**

```
make lint && make typecheck && make test
git add src/metatron/retrieval/search.py src/metatron/retrieval/channels.py tests/unit/retrieval/test_freshness_filter.py
git commit -m "feat(MTRNIX-313): retrieval-side freshness filter pushdown, flag-gated"
```

---

### Task 12: Scoring — add freshness signal (weight-gated, default 0.0)

**Files:**
- Modify: `src/metatron/retrieval/scoring.py`
- Modify: `src/metatron/retrieval/search.py`
- Create: `tests/unit/retrieval/test_scoring_with_freshness.py`

- [ ] **Step 1: TDD.**

```python
"""compute_signal_score with freshness weight (MTRNIX-313)."""
from metatron.retrieval.scoring import compute_signal_score


def test_freshness_weight_zero_is_identical_to_phase_a() -> None:
    before = compute_signal_score(
        {"dense": 0.5, "graph": 0.3, "metadata": 0.4},
        recency=0.6, balance=0.8,
    )
    after = compute_signal_score(
        {"dense": 0.5, "graph": 0.3, "metadata": 0.4},
        recency=0.6, balance=0.8,
        freshness=0.2, freshness_weight=0.0,
    )
    assert before == after


def test_freshness_contributes_when_weight_positive() -> None:
    s_fresh = compute_signal_score(
        {"dense": 0.5}, recency=0.5, balance=0.5,
        freshness=1.0, freshness_weight=0.3,
    )
    s_stale = compute_signal_score(
        {"dense": 0.5}, recency=0.5, balance=0.5,
        freshness=0.2, freshness_weight=0.3,
    )
    assert s_fresh > s_stale
```

- [ ] **Step 2: Extend `compute_signal_score` signature.**

Add `freshness: float = 1.0`, `freshness_weight: float = 0.0`. Update the formula + `weight_sum`:

```python
raw = (
    dense_weight * vector
    + graph_weight * graph
    + metadata_weight * metadata
    + recency_weight * recency
    + balance_weight * balance
    + freshness_weight * freshness
)
weight_sum = (
    dense_weight + graph_weight + metadata_weight
    + recency_weight + balance_weight + freshness_weight
)
```

- [ ] **Step 3: Wire into `search.py`.**

After the merged-candidates pool is assembled, batch-fetch `raw_documents.freshness_score` for distinct `doc_label`s in the pool (PG query, WHERE workspace_id + id ANY()). Build a dict `doc_label → freshness_score`. When calling `compute_signal_score`, pass `freshness=dict.get(doc_label, 1.0)` + `freshness_weight=settings.freshness_weight`.

If the PG lookup fails, fall back to `1.0` per doc — scoring is graceful.

- [ ] **Step 4: Run tests + commit.**

```
make lint && make typecheck && make test
git add src/metatron/retrieval/scoring.py src/metatron/retrieval/search.py tests/unit/retrieval/test_scoring_with_freshness.py
git commit -m "feat(MTRNIX-313): scoring — freshness signal, weight default 0.0"
```

---

### Task 13: Integration tests

**Files:**
- Create: `tests/integration/ingestion/freshness/__init__.py`
- Create: `tests/integration/ingestion/freshness/test_end_to_end_raw_document.py`
- Create: `tests/integration/retrieval/test_search_with_freshness_filter.py`

- [ ] **Step 1: End-to-end KB freshness test.**

Flow: `freshness_enabled=true, freshness_kb_enabled=true`. Ingest two KB docs via `upsert_raw_documents`. Trigger the producer. Run `await worker.run_once(10)`. Assert:

- `raw_documents.evidence_count` > 0 on the one that had a similar sibling.
- A `:Document-[:RELATED_TO]-:Document` edge exists in Neo4j.
- `review_entries` row exists with `target_kind="raw_document"` if similarity >=0.85.
- `machine_events` rows with `target_kind="raw_document"`.
- Qdrant chunk payload carries `status="active"` (not yet transitioning to STALE because `updated_at` is fresh).

- [ ] **Step 2: Filter-enabled search test.**

Two docs. Set one to `status='archived'` via `update_raw_document_lifecycle`, mirror the change into Qdrant payload via `sync_downstream_stores`. Query via `hybrid_search_and_answer`. With filter flag off, both docs appear; with it on, only the ACTIVE one does.

- [ ] **Step 3: Run.**

```
make test-all
```

- [ ] **Step 4: Commit.**

```
git add tests/integration/
git commit -m "test(MTRNIX-313): integration — end-to-end KB freshness + search filter"
```

---

### Task 14: Pre-flight — lint, typecheck, test, eval-compare

- [ ] **Step 1:** `make lint`
- [ ] **Step 2:** `make typecheck`
- [ ] **Step 3:** `make test`
- [ ] **Step 4:** `make test-all` (integration).
- [ ] **Step 5:** `make migrate` on a fresh DB: verify upgrade clean.
- [ ] **Step 6:** `make eval-compare` with `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED=false` — confirms no accidental regression from the producer / stage refactor paths (they shouldn't touch retrieval).
- [ ] **Step 7:** `make eval-compare` with `METATRON_FRESHNESS_KB_SEARCH_FILTER_ENABLED=true` — captures the "post-flip" baseline. Record the delta in the PR description. **Noise band: ±0.5 pp nDCG@10 (agreed 2026-04-22 by team lead). If delta exceeds the band, DO NOT flip the filter flag in prod. Schema + worker can still ship.**
- [ ] **Step 8:** Smoke tests:
  - `METATRON_FRESHNESS_ENABLED=false python -m metatron.memory.freshness` → logs `freshness.disabled.exit`.
  - `METATRON_FRESHNESS_ENABLED=true METATRON_FRESHNESS_KB_ENABLED=true python -m metatron.memory.freshness` → enters poll loop; Ctrl-C exits cleanly.
  - `METATRON_FRESHNESS_ENABLED=true METATRON_FRESHNESS_KB_ENABLED=false` → only memory jobs get produced and processed.
- [ ] **Step 9:** Backward-compat smoke:
  - Run a connector sync with all freshness flags off. Assert zero LPUSH to `freshness:queue:*` (grep the Redis MONITOR output).

---

### Task 15: Documentation updates (documenter teammate, post-approval)

**Files (documenter step only, do NOT touch in coder):**
- Modify: `CLAUDE.md` (root) — add new env vars, update "Key Config" and "External Agent Integration Surfaces" if affected; add section summary for the shared `freshness/` module.
- Modify: `src/metatron/memory/.claude/CLAUDE.md` — note the relocation of shared code to `metatron.freshness.*`; memory keeps only `target_memory.py`, `producer.py`, `worker.py`, `__main__.py`.
- Modify: `src/metatron/retrieval/.claude/claude.md` — add freshness signal + filter pushdown to the pipeline diagram.
- Modify: `src/metatron/ingestion/.claude/claude.md` — add `freshness/` submodule section + producer wire-up description.
- Modify: `src/metatron/storage/.claude/claude.md` — document new `raw_documents` columns, `update_raw_document_lifecycle`, `update_payload_by_doc_label`, `raw_document_graph`, file rename.
- Modify: `CHANGELOG.md` — `- feat: KB freshness worker (Phase B) (MTRNIX-313)` entry under `[Unreleased]`.

Documenter commits separately with `docs(MTRNIX-313): update documentation` (no Co-Authored-By, per user preference).

---

## Acceptance criteria (reviewer checklist)

Identical to the spec's "Acceptance criteria" list. Reproduced here for convenience:

1. `make lint` zero errors.
2. `make typecheck` zero errors.
3. `make test` all green, including new + Phase A regression guard.
4. `make test-all` all green.
5. `make migrate` clean upgrade + `alembic downgrade -1 && alembic upgrade head` round-trip.
6. All three KB flags off (default): byte-identical behaviour to pre-branch (zero Redis traffic from ingestion path verified).
7. `FRESHNESS_ENABLED=true, FRESHNESS_KB_ENABLED=true`: end-to-end KB job processed (integration test).
8. `FRESHNESS_KB_SEARCH_FILTER_ENABLED=true`: ARCHIVED/SUPERSEDED excluded from search (integration test).
9. `make eval-compare` with filter flag on — no regression beyond ±0.5 pp nDCG@10 (agreed 2026-04-22).
10. Every new PG query/Redis key/Qdrant filter carries `workspace_id`.
11. No new imports from `agent/`, `channels/`, `api/routes/chat.py`, `api/routes/finops.py` into new modules.
12. `interfaces.py` + `events.py` unchanged.
13. Phase A memory-freshness tests still green.

---

## Concerns flagged for the team lead

1. **Column rename on `review_entries` (`record_id → target_id`).** Migration 018 handles the DB rename; Python dataclass keeps `record_id` as a settable alias. If the enterprise Control Center plugin queries `review_entries` by column name directly (not through `FreshnessStore`), it will need a parallel update. **ENTERPRISE COORDINATION: flag in PR description.**
2. **Event payloads now carry both `target_kind` values.** Subscribers to `FRESHNESS_DECISION_APPLIED` / `FRESHNESS_REVIEW_CREATED` will receive KB events after Phase B. Non-breaking; subscribers should filter on `target_kind` if they only want memory. **ENTERPRISE COURTESY HEADS-UP in PR description.**
3. **Eval regression on filter flag flip.** The schema/worker/producer changes are safe to ship without flipping the filter flag. If `make eval-compare` with the filter flag on regresses beyond the noise band, **do not flip the filter flag in prod** — the schema + worker can still land, and the filter flag remains a deployment decision. Plan's Task 14 captures this gating.
4. **Qdrant payload backfill.** Existing chunks lack the `status` / `freshness_score` payload fields until the FreshnessMonitor first touches their parent doc. Backfill is optional (script included, not runtime-required). With the filter flag off, no behavioural impact; with it on and no backfill, ARCHIVED-but-unmirrored docs would still appear until the worker catches up — mitigated by scheduling the backfill before the filter flag flip in staging.
5. **Bulk STALE on first run.** Mitigated via the age-gate (`last_freshness_run_at`). KB's `freshness_kb_stale_after_days` defaults to 90 (vs memory's 30). Filter does not exclude STALE (only ARCHIVED/SUPERSEDED) — so even if many docs become STALE, search recall is unaffected. Only scoring is (which is 0-weighted by default).
6. **Single worker process serves both pipelines.** Confirmed as a deliberate decision (one profile, one docker service). If production shows starvation patterns, split into two workers later — `target_kind` already provides the information for sharding the queue.
7. **No `core/interfaces.py` promotion of `FreshnessTarget`.** Deliberate: Protocol lives in `freshness/targets.py`. Promote in a follow-up after the shape has been stable across a release cycle — premature promotion forces enterprise coordination for every tweak.

### Critical files for implementation

- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/core/models.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/migrations/versions/018_kb_freshness_lifecycle.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/freshness/targets.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/ingestion/freshness/target_raw_document.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/memory/freshness/worker.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/retrieval/search.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/retrieval/channels.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/retrieval/scoring.py`
