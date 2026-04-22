# Freshness Worker for Agent Memory (Phase A) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the metamemory freshness worker concept onto metatron-core's `MemoryRecord` surface. Introduce a bounded, observable, pausable, replayable pipeline (Linker → Reconciler → FreshnessMonitor → Curator → DecisionEngine) driven by a Redis-backed per-workspace queue and a standalone worker process. Phase A is agent memory only; KB (Phase B) is MTRNIX-313.

**Architecture:** New L3 sub-module `src/metatron/memory/freshness/` with five stage modules, a Redis coordination layer, a worker entry-point (`python -m metatron.memory.freshness`), and a DecisionEngine protocol backed by `llm/provider.py`. Two new PG tables (`review_entries`, `machine_events`) + seven lifecycle columns on `memory_records` land in Alembic migration 016. Feature flag `METATRON_FRESHNESS_ENABLED=false` by default; worker process not launched in prod until SLM bench-off.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy async (asyncpg), `redis.asyncio` (existing `RedisStore` extended with list/lock primitives), `AsyncQdrantClient`, Neo4j bolt (sync, called via `asyncio.to_thread`), `llm/provider.py` (sync provider called via `asyncio.to_thread`), structlog, `prometheus-client` (confirm availability; see concerns), pytest (`asyncio_mode = "auto"`).

**Jira:** MTRNIX-304 (Phase A)
**Parent epic:** MTRNIX-227 — Agent Memory System (WS1)
**Siblings:** MTRNIX-310 (merged), MTRNIX-313 (Phase B — blocked by 304), MTRNIX-314 (MCP `status`/review queue — blocked by 304)
**Spec:** `docs/superpowers/specs/2026-04-20-freshness-worker-agent-memory-design.md`
**Branch:** `feature/MTRNIX-304`

---

## Layer Boundary Summary

All new code lives under `src/metatron/memory/freshness/` (L3 submodule of `memory/`).

| File | Layer | Allowed imports |
|---|---|---|
| `memory/freshness/models.py` | L3 dataclasses | `core.models`, stdlib |
| `memory/freshness/coordination.py` | L3 | `core.config`, `storage.redis` |
| `memory/freshness/linker.py` | L3 | `core`, `storage` (memory_postgres, memory_qdrant, memory_graph), `memory.service` (sibling) |
| `memory/freshness/reconciler.py` | L3 | same as linker |
| `memory/freshness/monitor.py` | L3 | `core`, `storage` |
| `memory/freshness/curator.py` | L3 | `core`, `storage` |
| `memory/freshness/decision_engine.py` | L3 | `core`, `llm.provider` (sibling L3) |
| `memory/freshness/producer.py` | L3 | `core.config`, `memory.freshness.coordination` |
| `memory/freshness/worker.py` | L3 | all of the above + `memory.service` |
| `memory/freshness/__main__.py` | L3 | `memory.freshness.worker` |
| `memory/freshness/metrics.py` | L3 | stdlib, `prometheus_client` |
| `storage/memory_freshness_pg.py` | L1 | `core.models`, SQLAlchemy (new store for `review_entries`, `machine_events`) |
| `storage/redis.py` (extend) | L1 | `redis.asyncio` |
| `core/models.py` (extend) | L0 | stdlib only |
| `core/config.py` (extend) | L0 | pydantic-settings |
| `core/events.py` (extend) | L0 | stdlib |
| `core/exceptions.py` (extend) | L0 | stdlib |

**Not touched:** `agent/`, `channels/`, `api/`, `skills/`, `workspaces/`. Worker is a separate process — no new FastAPI routes. `interfaces.py` is NOT extended in Phase A (rationale below).

**No upward imports.** The producer hook lives under `memory/freshness/producer.py`; `mcp/tools/memory_store.py` et al. import it (L3→L3 sibling, allowed).

---

## Config Vars (all with `METATRON_` prefix, registered in `src/metatron/core/config.py`)

| Env var (alias) | Settings field | Default | Purpose |
|---|---|---|---|
| `METATRON_FRESHNESS_ENABLED` | `freshness_enabled` | `False` | Master feature flag. When `False`: producer is a no-op, worker exits immediately if started. |
| `METATRON_FRESHNESS_POLL_SECONDS` | `freshness_poll_seconds` | `2.0` | Sleep between empty-queue polls. |
| `METATRON_FRESHNESS_MAX_JOBS_PER_ITERATION` | `freshness_max_jobs_per_iteration` | `20` | Batch size for `run_once`. |
| `METATRON_FRESHNESS_LOCK_TTL_SECONDS` | `freshness_lock_ttl_seconds` | `30` | SET NX EX TTL for per-stage-per-item locks. |
| `METATRON_FRESHNESS_STALE_AFTER_DAYS` | `freshness_stale_after_days` | `30` | Monitor stale threshold. |
| `METATRON_FRESHNESS_DECISION_CONFIDENCE_THRESHOLD` | `freshness_decision_confidence_threshold` | `0.7` | Below → `ReviewEntry`, above → auto-apply. |
| `METATRON_FRESHNESS_LLM_MODEL` | `freshness_llm_model` | `qwen2.5-4b-instruct-q4` | SLM model name. |
| `METATRON_FRESHNESS_LLM_PROVIDER` | `freshness_llm_provider` | `""` (empty → reuse `LLM_PROVIDER`) | Provider override for freshness (allows worker to hit a separate Ollama). |
| `METATRON_FRESHNESS_LLM_API_BASE_URL` | `freshness_llm_api_base_url` | `""` (empty → fallback to rule-based) | When empty, DecisionEngine uses `RuleBasedDecisionEngine` only. |
| `METATRON_FRESHNESS_LLM_API_KEY` | `freshness_llm_api_key` | `""` | Optional API key. |
| `METATRON_FRESHNESS_LINKER_THRESHOLD` | `freshness_linker_threshold` | `0.6` | Cosine threshold in Linker. |
| `METATRON_FRESHNESS_RECONCILER_THRESHOLD` | `freshness_reconciler_threshold` | `0.85` | Cosine threshold in Reconciler. |
| `METATRON_FRESHNESS_BACKOFF_BASE_SECONDS` | `freshness_backoff_base_seconds` | `2.0` | Worker error backoff base. |
| `METATRON_FRESHNESS_BACKOFF_MAX_SECONDS` | `freshness_backoff_max_seconds` | `60.0` | Worker error backoff ceiling. |
| `METATRON_FRESHNESS_MAX_CONSECUTIVE_ERRORS` | `freshness_max_consecutive_errors` | `10` | Hard-exit threshold. |

No per-workspace overrides in Phase A. Workspaces are enumerated from the PG `workspaces` table each iteration (see `worker.py` step).

---

## Event Constants (added to `src/metatron/core/events.py`)

```
FRESHNESS_JOB_ENQUEUED      = "freshness_job_enqueued"
FRESHNESS_JOB_PROCESSED     = "freshness_job_processed"
FRESHNESS_DECISION_APPLIED  = "freshness_decision_applied"
FRESHNESS_REVIEW_CREATED    = "freshness_review_created"
```

**Coordination concern for enterprise repo:** these are NEW event names. The enterprise plugin may want to subscribe to `FRESHNESS_DECISION_APPLIED` (audit) and `FRESHNESS_REVIEW_CREATED` (review queue UI in Control Center). Flag this in the PR description and notify the enterprise maintainer before merging. This is a coordination point but NOT a breaking change — existing constants are untouched.

**Interfaces.py:** NOT extended in Phase A. The spec calls out a `DecisionEngine` Protocol, but the spec explicitly keeps it in `memory/freshness/decision_engine.py` (not in `core/interfaces.py`). This avoids premature lock-in on the exact shape and keeps Phase A blast radius small. If MTRNIX-313 shows KB needs the same protocol, we lift it into `core/interfaces.py` then.

---

## Backward Compatibility Guarantee

When `METATRON_FRESHNESS_ENABLED=false` (the default):
- `memory_store` / `memory_batch_store` / `memory_update` MCP tools call `producer.enqueue_if_enabled()` which short-circuits to a no-op — zero Redis traffic, zero latency change.
- Alembic migration 016 adds columns with backward-compatible defaults: `status='ACTIVE'`, `freshness_score=0.5`, `evidence_count=0`, all nullable fields `NULL`. Existing rows look "active" to any future search.
- `MemoryService.save()` / `search()` / `list_records()` behaviour is unchanged — new columns are ignored by current queries. `memory_search` is NOT status-aware until MTRNIX-314.
- Worker process is NOT added to `docker compose up` default. It lives under an opt-in profile (`--profile freshness`). `make dev` unchanged.
- No existing test should fail. Migration upgrade+downgrade must be exercised in test suite (step 2 below).

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `src/metatron/core/models.py` | Add `MemoryStatus` enum; extend `MemoryRecord` with 7 lifecycle fields; add `ReviewEntry`, `MachineEvent`, `FreshnessJob`, `FreshnessDecision` dataclasses |
| Modify | `src/metatron/core/config.py` | Register 14 `METATRON_FRESHNESS_*` env vars |
| Modify | `src/metatron/core/events.py` | Add 4 `FRESHNESS_*` event constants + payload conventions in docstrings |
| Modify | `src/metatron/core/exceptions.py` | Add `FreshnessError` (extends `MetatronError`) |
| Create | `migrations/versions/016_freshness_lifecycle.py` | Alter `memory_records` (7 cols); create `review_entries` + `machine_events`; indexes |
| Modify | `src/metatron/storage/redis.py` | Add `lpush`, `brpop` (with timeout), `rpop_batch`, `acquire_lock`, `release_lock`, `heartbeat_lock`, `write_checkpoint`, `read_checkpoint`, `queue_depth` methods |
| Modify | `src/metatron/storage/memory_postgres.py` | Row mapper to read new columns; add `update_lifecycle(record_id, status=, freshness_score=, superseded_by=, evidence_count=, verification_state=)` |
| Create | `src/metatron/storage/memory_freshness_pg.py` | `FreshnessPostgresStore` — CRUD for `review_entries`, append for `machine_events`, list-by-target helper |
| Create | `src/metatron/memory/freshness/__init__.py` | Re-export `FreshnessWorker`, `FreshnessJob`, `FreshnessDecision`, `enqueue_job` |
| Create | `src/metatron/memory/freshness/__main__.py` | `python -m metatron.memory.freshness` entry-point delegating to `worker.main()` |
| Create | `src/metatron/memory/freshness/models.py` | Re-export + freshness-only helpers (job (de)serialization JSON ↔ FreshnessJob) |
| Create | `src/metatron/memory/freshness/coordination.py` | `CoordinationStore` — per-workspace queue keys, locks, checkpoints. Uses async `RedisStore`. |
| Create | `src/metatron/memory/freshness/producer.py` | `enqueue_if_enabled(workspace_id, record_id, event_type)` — called by MCP tools |
| Create | `src/metatron/memory/freshness/linker.py` | `Linker` — Qdrant cosine search → `evidence_count` update + Neo4j edges |
| Create | `src/metatron/memory/freshness/reconciler.py` | `Reconciler` — duplicate detection → `ReviewEntry` + ALIAS edge |
| Create | `src/metatron/memory/freshness/monitor.py` | `FreshnessMonitor` — valid_until / superseded_by / stale threshold → status transitions |
| Create | `src/metatron/memory/freshness/curator.py` | `Curator` — CANDIDATE + evidence_count≥1 → ACTIVE + `auto_curated` tag |
| Create | `src/metatron/memory/freshness/decision_engine.py` | `DecisionEngine` Protocol, `RuleBasedDecisionEngine`, `LLMBackedDecisionEngine`, `build_default_decision_engine()` |
| Create | `src/metatron/memory/freshness/worker.py` | `FreshnessWorker` async class; `run_once`; `main()` with backoff loop |
| Create | `src/metatron/memory/freshness/metrics.py` | Prometheus counters/gauges/histograms (gated behind `prometheus_client` import) |
| Modify | `src/metatron/memory/service.py` | Hook `producer.enqueue_if_enabled()` after `save` / `update` / `delete` / `cache_session` |
| Modify | `src/metatron/mcp/tools/memory_store.py` | Emit job after successful `save` (via `MemoryService` hook — no direct call needed) |
| Modify | `src/metatron/mcp/tools/memory_batch_store.py` | Same (hook inside `MemoryService.save` covers it, confirm behaviour) |
| Modify | `src/metatron/mcp/tools/memory_update.py` | Emit `content_changed` or `metadata_changed` when applicable |
| Modify | `docker-compose.yml` | Add optional `freshness-worker` service under `--profile freshness` |
| Create | `tests/unit/memory/__init__.py` | Package marker |
| Create | `tests/unit/memory/freshness/__init__.py` | Package marker |
| Create | `tests/unit/memory/freshness/test_models.py` | Lifecycle fields + enum parsing |
| Create | `tests/unit/memory/freshness/test_coordination.py` | Lock re-entry, checkpoint round-trip, BRPOP batch edges — mocked Redis |
| Create | `tests/unit/memory/freshness/test_producer.py` | No-op when flag off; LPUSH payload when flag on |
| Create | `tests/unit/memory/freshness/test_linker.py` | Cosine threshold behaviour; no-op without embedding provider |
| Create | `tests/unit/memory/freshness/test_reconciler.py` | Duplicate flagging → `ReviewEntry`; idempotent second-run |
| Create | `tests/unit/memory/freshness/test_monitor.py` | valid_until expired; superseded_by present; stale threshold |
| Create | `tests/unit/memory/freshness/test_curator.py` | CANDIDATE→ACTIVE + `auto_curated` tag added |
| Create | `tests/unit/memory/freshness/test_decision_engine.py` | JSON parse happy path; malformed → fallback; below threshold → review |
| Create | `tests/unit/memory/freshness/test_worker.py` | Single iteration; empty queue; backoff escalation; hard-exit after N errors |
| Create | `tests/unit/storage/test_redis_coordination.py` | LPUSH/BRPOP/lock primitives on mocked Redis client |
| Create | `tests/unit/storage/test_memory_freshness_pg.py` | `FreshnessPostgresStore` CRUD against in-memory SQLAlchemy mock |
| Create | `tests/integration/memory/__init__.py` | Package marker |
| Create | `tests/integration/memory/freshness/__init__.py` | Package marker |
| Create | `tests/integration/memory/freshness/test_end_to_end.py` | Enqueue → worker iteration → PG status transition + MachineEvent rows + Qdrant payload refresh |
| Create | `tests/integration/memory/freshness/test_reconciler_qdrant.py` | Duplicate detection against live Qdrant |
| Modify | `tests/unit/conftest.py` | `freshness_settings` fixture (flag-on overrides) |
| Create | `docs/superpowers/plans/2026-04-20-freshness-worker-agent-memory.md` | This plan |

---

## Ordered Tasks

---

### Task 1: Data model — core dataclasses and enums

**Files:**
- Modify: `src/metatron/core/models.py`
- Modify: `src/metatron/core/exceptions.py`

- [ ] **Step 1: Add `MemoryStatus` enum**

In `core/models.py`, after the `MemoryScope` enum:

```python
class MemoryStatus(StrEnum):
    """Lifecycle status of a MemoryRecord (freshness Phase A)."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    STALE = "stale"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    CONFLICTED = "conflicted"
    REVIEW_NEEDED = "review_needed"
```

- [ ] **Step 2: Extend `MemoryRecord` with 7 lifecycle fields**

Append after `metadata`:

```python
    status: MemoryStatus = MemoryStatus.ACTIVE            # backwards-compat default for legacy rows
    freshness_score: float = 0.5
    superseded_by: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    evidence_count: int = 0
    verification_state: str | None = None
    updated_at: datetime | None = None                    # already written by PG; now exposed in dataclass
```

Note: `updated_at` is already written by `MemoryPostgresStore.save` but not round-tripped into the dataclass. Row mapper update lands in Task 3.

- [ ] **Step 3: Add freshness dataclasses**

Append a new section "Freshness (MTRNIX-304)":

```python
@dataclass
class ReviewEntry:
    id: str = field(default_factory=lambda: uuid4().hex)
    workspace_id: str = ""
    record_id: str = ""
    reason: str = ""                    # "possible_duplicate" | "possible_contradiction" | "low_confidence_decision"
    related_record_id: str | None = None
    content: str = ""
    confidence: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class MachineEvent:
    id: str = field(default_factory=lambda: uuid4().hex)
    workspace_id: str = ""
    event_type: str = ""                # "freshness_job_received" | "freshness_job_processed" | ...
    actor: str = "freshness_worker"
    target_kind: str = "memory_record"
    target_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class FreshnessJob:
    workspace_id: str = ""
    event_type: str = ""                # "knowledge_changed" | "content_changed" | "scheduled_scan"
    target_kind: str = "memory_record"
    target_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class FreshnessDecision:
    action: str = "tag"
    confidence: float = 0.0
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    rationale: str = ""
```

- [ ] **Step 4: Add exception**

In `core/exceptions.py`, under `AgentMemoryError`:

```python
class FreshnessError(MetatronError):
    """Freshness pipeline failure (stage error, LLM parse failure, lock contention)."""
```

- [ ] **Step 5: Verify imports**

```
python -c "from metatron.core.models import MemoryRecord, MemoryStatus, ReviewEntry, MachineEvent, FreshnessJob, FreshnessDecision; print('OK')"
python -c "from metatron.core.exceptions import FreshnessError; print('OK')"
```
Expected: `OK` twice.

- [ ] **Step 6: Commit**

```
git add src/metatron/core/models.py src/metatron/core/exceptions.py
git commit -m "feat(MTRNIX-304): add MemoryStatus + freshness dataclasses to core.models"
```

**Acceptance:** new types importable, all defaults backwards-compatible, no other module needs to change yet.

---

### Task 2: Alembic migration 016 — lifecycle columns + freshness tables

**Files:**
- Create: `migrations/versions/016_freshness_lifecycle.py`

Revision chain: `down_revision = "015"`, `revision = "016"`.

- [ ] **Step 1: Write migration**

```python
"""Freshness lifecycle columns + review_entries + machine_events (MTRNIX-304).

Revision ID: 016
Revises: 015
Create Date: 2026-04-20
"""
from __future__ import annotations
from typing import TYPE_CHECKING
import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("memory_records", sa.Column("status", sa.Text, nullable=False, server_default="active"))
    op.add_column("memory_records", sa.Column("freshness_score", sa.Float, nullable=False, server_default=sa.text("0.5")))
    op.add_column("memory_records", sa.Column("superseded_by", sa.Text, nullable=True))
    op.add_column("memory_records", sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memory_records", sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("memory_records", sa.Column("evidence_count", sa.Integer, nullable=False, server_default=sa.text("0")))
    op.add_column("memory_records", sa.Column("verification_state", sa.Text, nullable=True))

    op.create_index("ix_memory_records_status", "memory_records", ["workspace_id", "status"])
    op.create_index(
        "ix_memory_records_valid_until",
        "memory_records",
        ["workspace_id", "valid_until"],
        postgresql_where=sa.text("valid_until IS NOT NULL"),
    )

    op.create_table(
        "review_entries",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("record_id", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("related_record_id", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("confidence", sa.Float, nullable=False, server_default=sa.text("0.0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_review_entries_workspace", "review_entries", ["workspace_id", "created_at"])
    op.create_index("ix_review_entries_record", "review_entries", ["workspace_id", "record_id"])

    op.create_table(
        "machine_events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("actor", sa.Text, nullable=False, server_default="freshness_worker"),
        sa.Column("target_kind", sa.Text, nullable=False, server_default="memory_record"),
        sa.Column("target_id", sa.Text, nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_machine_events_workspace_time", "machine_events", ["workspace_id", "created_at"])
    op.create_index("ix_machine_events_target", "machine_events", ["target_kind", "target_id", "created_at"])
    op.create_index("ix_machine_events_type", "machine_events", ["workspace_id", "event_type", "created_at"])


def downgrade() -> None:
    op.drop_table("machine_events")
    op.drop_table("review_entries")
    op.drop_index("ix_memory_records_valid_until", table_name="memory_records")
    op.drop_index("ix_memory_records_status", table_name="memory_records")
    op.drop_column("memory_records", "verification_state")
    op.drop_column("memory_records", "evidence_count")
    op.drop_column("memory_records", "valid_until")
    op.drop_column("memory_records", "valid_from")
    op.drop_column("memory_records", "superseded_by")
    op.drop_column("memory_records", "freshness_score")
    op.drop_column("memory_records", "status")
```

- [ ] **Step 2: Dry-run upgrade**

```
alembic upgrade head --sql > /tmp/016.sql && head -50 /tmp/016.sql
```
Expected: ALTER TABLE + CREATE TABLE statements visible.

- [ ] **Step 3: Apply and sanity check**

```
make migrate
psql "$METATRON_POSTGRES_DSN" -c "\d memory_records" | grep -E "status|freshness_score"
psql "$METATRON_POSTGRES_DSN" -c "\d review_entries"
psql "$METATRON_POSTGRES_DSN" -c "\d machine_events"
```

- [ ] **Step 4: Round-trip test**

```
alembic downgrade 015 && alembic upgrade 016
```

- [ ] **Step 5: Commit**

```
git add migrations/versions/016_freshness_lifecycle.py
git commit -m "feat(MTRNIX-304): alembic 016 — freshness lifecycle columns + tables"
```

**Acceptance:** `make migrate` applies cleanly on a fresh DB and on an existing DB carrying populated `memory_records`. Downgrade works. Existing rows land with `status='active'`, `freshness_score=0.5`.

---

### Task 3: Storage — extend `MemoryPostgresStore`, add `FreshnessPostgresStore`, extend `RedisStore`

**Files:**
- Modify: `src/metatron/storage/memory_postgres.py`
- Create: `src/metatron/storage/memory_freshness_pg.py`
- Modify: `src/metatron/storage/redis.py`
- Create: `tests/unit/storage/test_memory_freshness_pg.py`
- Create: `tests/unit/storage/test_redis_coordination.py`

- [ ] **Step 1: Update `_RECORD_COLUMNS` and `_row_to_record` in `memory_postgres.py`**

Include the 7 new columns + `updated_at`. Map to the extended `MemoryRecord`. Keep existing save path: INSERT with `status='active'` + defaults when record dataclass carries defaults (existing call sites unaffected).

- [ ] **Step 2: Add `update_lifecycle()`**

```python
async def update_lifecycle(
    self,
    workspace_id: str,
    record_id: str,
    *,
    status: MemoryStatus | None = None,
    freshness_score: float | None = None,
    superseded_by: str | None = None,
    evidence_count: int | None = None,
    verification_state: str | None = None,
    valid_until: datetime | None = None,
) -> MemoryRecord | None:
    ...  # UPDATE ... RETURNING pattern (same as existing update())
```

Called by FreshnessMonitor, Curator, DecisionEngine.apply.

- [ ] **Step 3: Create `FreshnessPostgresStore`**

`src/metatron/storage/memory_freshness_pg.py`:

```python
class FreshnessPostgresStore:
    """Async PG store for review_entries and machine_events."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def save_review_entry(self, entry: ReviewEntry) -> ReviewEntry: ...
    async def list_review_entries(self, workspace_id: str, *, record_id: str | None = None) -> list[ReviewEntry]: ...
    async def save_machine_event(self, event: MachineEvent) -> MachineEvent: ...
    async def list_events_for_target(
        self, workspace_id: str, target_kind: str, target_id: str,
    ) -> list[MachineEvent]: ...
```

All queries carry `workspace_id`.

- [ ] **Step 4: Extend `storage/redis.py` with list + lock primitives**

Add these methods to `RedisStore`:

```python
async def lpush(self, key: str, value: str) -> int: ...
async def rpop_batch(self, key: str, max_items: int) -> list[str]:
    """Atomic multi-pop via Lua (or pipelined RPOP loop as fallback)."""
async def llen(self, key: str) -> int: ...
async def scan_keys(self, match: str, count: int = 100) -> list[str]: ...  # for queue enumeration
async def acquire_lock(self, key: str, ttl_seconds: int, token: str) -> bool:
    """SET key token NX EX ttl. Returns True if acquired."""
async def heartbeat_lock(self, key: str, ttl_seconds: int, token: str) -> bool:
    """Extend TTL only if token matches. Lua script."""
async def release_lock(self, key: str, token: str) -> bool:
    """DEL only if token matches. Lua script."""
async def write_checkpoint(self, key: str, value: str, ttl: int = 86400) -> None: ...
async def read_checkpoint(self, key: str) -> str | None: ...
```

All use `self._client` (async `redis.asyncio.Redis`). Lua scripts are strings defined at module level.

- [ ] **Step 5: Unit tests**

`tests/unit/storage/test_redis_coordination.py` — mock `Redis` client, assert command sequences. `tests/unit/storage/test_memory_freshness_pg.py` — use `AsyncMock` wrapper on `AsyncEngine.begin()` (same pattern as `tests/unit/test_memory_update.py`).

- [ ] **Step 6: Commit**

```
git add src/metatron/storage/memory_postgres.py src/metatron/storage/memory_freshness_pg.py src/metatron/storage/redis.py tests/unit/storage/
git commit -m "feat(MTRNIX-304): storage — lifecycle update, freshness PG store, redis queue/lock primitives"
```

**Acceptance:** new unit tests pass. `ruff` + `mypy` clean.

---

### Task 4: Config and event registration

**Files:**
- Modify: `src/metatron/core/config.py`
- Modify: `src/metatron/core/events.py`

- [ ] **Step 1: Add 14 fresh settings fields** (see Config table above) at the end of the `Settings` class, before `cors_origins_list` property.

- [ ] **Step 2: Add 4 event constants** to `core/events.py`, with docstring payload conventions matching `MEMORY_STORED` style:

```
# Freshness events (MTRNIX-304)
# Payload conventions:
#   freshness_job_enqueued     -> {"workspace_id", "record_id", "event_type"}
#   freshness_job_processed    -> {"workspace_id", "record_id", "decision_action", "duration_ms"}
#   freshness_decision_applied -> {"workspace_id", "record_id", "action", "confidence"}
#   freshness_review_created   -> {"workspace_id", "record_id", "reason", "review_entry_id"}
FRESHNESS_JOB_ENQUEUED = "freshness_job_enqueued"
FRESHNESS_JOB_PROCESSED = "freshness_job_processed"
FRESHNESS_DECISION_APPLIED = "freshness_decision_applied"
FRESHNESS_REVIEW_CREATED = "freshness_review_created"
```

- [ ] **Step 3: Test**

```
python -c "from metatron.core.config import Settings; s = Settings(); assert s.freshness_enabled is False; assert s.freshness_poll_seconds == 2.0; print('OK')"
python -c "from metatron.core.events import FRESHNESS_JOB_ENQUEUED; print(FRESHNESS_JOB_ENQUEUED)"
```

- [ ] **Step 4: Flag enterprise coordination**

In the commit message body, add: "New event constants — enterprise repo may want to subscribe for Control Center review queue / audit; no breaking change to existing event names."

- [ ] **Step 5: Commit**

```
git add src/metatron/core/config.py src/metatron/core/events.py
git commit -m "feat(MTRNIX-304): register freshness config + event constants

New event names FRESHNESS_JOB_ENQUEUED, FRESHNESS_JOB_PROCESSED,
FRESHNESS_DECISION_APPLIED, FRESHNESS_REVIEW_CREATED — enterprise plugin
may subscribe; no existing event names changed."
```

---

### Task 5: Coordination layer (`memory/freshness/coordination.py`)

**Files:**
- Create: `src/metatron/memory/freshness/__init__.py`
- Create: `src/metatron/memory/freshness/coordination.py`
- Create: `tests/unit/memory/__init__.py`
- Create: `tests/unit/memory/freshness/__init__.py`
- Create: `tests/unit/memory/freshness/test_coordination.py`

- [ ] **Step 1: TDD — write failing tests**

`test_coordination.py` exercises: `enqueue_job` serializes to JSON and LPUSHes; `dequeue_batch` uses `rpop_batch` and deserializes; `acquire_lock` returns True once then False; `heartbeat` extends TTL; `release` uses token guard; `write_checkpoint`/`read_checkpoint` round-trip; `list_active_workspaces` returns keys matching `freshness:queue:*`.

- [ ] **Step 2: Implement `CoordinationStore`**

```python
class CoordinationStore:
    """Redis-backed coordination for the freshness pipeline.

    Queue key:        freshness:queue:{workspace_id}
    Lock key:         freshness:{stage}:{record_id}
    Checkpoint key:   freshness:checkpoint:{stage}:{record_id}
    """

    def __init__(self, redis: RedisStore) -> None:
        self._redis = redis

    async def enqueue_job(self, job: FreshnessJob) -> None: ...
    async def dequeue_batch(self, workspace_id: str, max_items: int) -> list[FreshnessJob]: ...
    async def queue_depth(self, workspace_id: str) -> int: ...
    async def list_active_workspaces(self) -> list[str]: ...
    async def acquire_lock(self, stage: str, record_id: str, ttl: int) -> str | None:
        """Return a token if acquired, else None."""
    async def heartbeat(self, stage: str, record_id: str, ttl: int, token: str) -> bool: ...
    async def release(self, stage: str, record_id: str, token: str) -> None: ...
    async def write_checkpoint(self, stage: str, record_id: str, value: str) -> None: ...
    async def read_checkpoint(self, stage: str, record_id: str) -> str | None: ...
```

JSON serde at the boundary. Tokens are `uuid4().hex`. Lock-per-stage-per-item (so Linker and Reconciler can run in parallel on different items, but two workers cannot race on the same record within one stage).

- [ ] **Step 3: Run tests**

```
pytest tests/unit/memory/freshness/test_coordination.py -v
```

- [ ] **Step 4: Commit**

```
git add src/metatron/memory/freshness/__init__.py src/metatron/memory/freshness/coordination.py tests/unit/memory/
git commit -m "feat(MTRNIX-304): redis coordination store — per-workspace queue + per-stage locks"
```

---

### Task 6: Producer hook

**Files:**
- Create: `src/metatron/memory/freshness/producer.py`
- Create: `tests/unit/memory/freshness/test_producer.py`
- Modify: `src/metatron/memory/service.py`
- Modify: `src/metatron/mcp/tools/memory_update.py`

- [ ] **Step 1: TDD**

`test_producer.py`:
- `test_enqueue_if_enabled_noop_when_flag_off` — monkeypatch `get_settings().freshness_enabled=False`, assert no Redis call.
- `test_enqueue_if_enabled_lpushes_when_flag_on` — flag True, assert CoordinationStore receives job with correct payload.
- `test_enqueue_if_enabled_swallows_redis_errors` — Redis raises, producer logs warning, never raises (fail-soft — we never want freshness to break `memory_store`).

- [ ] **Step 2: Implement**

```python
# src/metatron/memory/freshness/producer.py
async def enqueue_if_enabled(
    workspace_id: str,
    record_id: str,
    event_type: str = "knowledge_changed",
    *,
    coordination: CoordinationStore | None = None,
) -> None:
    settings = get_settings()
    if not settings.freshness_enabled:
        return
    try:
        store = coordination or _build_default_coordination()
        await store.enqueue_job(FreshnessJob(
            workspace_id=workspace_id,
            event_type=event_type,
            target_kind="memory_record",
            target_id=record_id,
        ))
    except Exception:
        logger.warning("freshness.producer.enqueue_failed", record_id=record_id, exc_info=True)
```

- [ ] **Step 3: Wire into `MemoryService`**

In `memory/service.py`:
- `save()` — after successful PG+Qdrant write, call `enqueue_if_enabled(workspace_id, saved.id, "knowledge_changed")`.
- `cache_session()` — call `enqueue_if_enabled(workspace_id, record.id, "knowledge_changed")`.
- `delete()` — call `enqueue_if_enabled(workspace_id, record_id, "knowledge_deleted")` (reserved for future; worker in Phase A just skips these).
- `promote()` — call `enqueue_if_enabled(workspace_id, result.id, "scope_changed")`.

No change needed to `memory_store` / `memory_batch_store` MCP tools — `MemoryService.save` covers them.

- [ ] **Step 4: Wire into `memory_update.py`**

After successful `pg_store.update`, call `enqueue_if_enabled(..., event_type="content_changed" if content is not None else "metadata_changed")`.

- [ ] **Step 5: Confirm backward compatibility**

With `freshness_enabled=False` (default), the producer is a no-op — zero Redis traffic, zero latency change. Add a unit test asserting that `MemoryService.save()` still returns the saved record when Redis is unreachable (Redis errors are swallowed).

- [ ] **Step 6: Run tests**

```
pytest tests/unit/memory/freshness/test_producer.py tests/unit/test_memory_update.py tests/unit/test_memory_batch_store.py -v
```

- [ ] **Step 7: Commit**

```
git add src/metatron/memory/freshness/producer.py src/metatron/memory/service.py src/metatron/mcp/tools/memory_update.py tests/unit/memory/freshness/test_producer.py
git commit -m "feat(MTRNIX-304): producer hook — enqueue freshness job after memory writes"
```

---

### Task 7: Pipeline stages — Linker + Reconciler

**Files:**
- Create: `src/metatron/memory/freshness/linker.py`
- Create: `src/metatron/memory/freshness/reconciler.py`
- Create: `tests/unit/memory/freshness/test_linker.py`
- Create: `tests/unit/memory/freshness/test_reconciler.py`

- [ ] **Step 1: TDD tests for Linker**

Scenarios: record with 0 related (evidence_count stays 0); record with 2 cosine>0.6 matches (evidence_count=2, Neo4j `LINKED_TO` edges written via `asyncio.to_thread(save_memory_to_graph, ...)` best-effort); lock contention returns early without raising.

- [ ] **Step 2: Implement `Linker`**

Uses `MemoryQdrantStore.search` (existing) with a query = record's content, top_k=20, filter by workspace_id. Counts hits with score > `freshness_linker_threshold`. Calls `MemoryPostgresStore.update_lifecycle(..., evidence_count=...)`. Acquires lock `freshness:linker:{record_id}`. Writes checkpoint. Emits `freshness_stage_completed` MachineEvent.

- [ ] **Step 3: TDD tests for Reconciler**

Scenarios: exact-content duplicate in workspace → creates `ReviewEntry(reason="possible_duplicate")` + ALIAS edge; cosine>0.85 non-exact → same; idempotent second call does NOT create a second `ReviewEntry` (reuse existing matching entry); clean state writes `"clean"` checkpoint.

- [ ] **Step 4: Implement `Reconciler`**

Same pattern: lock, Qdrant search for very-high-similarity, branch on hit → write `ReviewEntry` via `FreshnessPostgresStore.save_review_entry`, call Neo4j `link_items` (best-effort via `asyncio.to_thread`), emit `FRESHNESS_REVIEW_CREATED` event if the app has an `EventBus` (worker can run without one; pass `EventBus | None = None` ctor arg).

- [ ] **Step 5: Run tests**

```
pytest tests/unit/memory/freshness/test_linker.py tests/unit/memory/freshness/test_reconciler.py -v
```

- [ ] **Step 6: Commit**

```
git add src/metatron/memory/freshness/linker.py src/metatron/memory/freshness/reconciler.py tests/unit/memory/freshness/test_linker.py tests/unit/memory/freshness/test_reconciler.py
git commit -m "feat(MTRNIX-304): Linker + Reconciler stages"
```

---

### Task 8: FreshnessMonitor + Curator

**Files:**
- Create: `src/metatron/memory/freshness/monitor.py`
- Create: `src/metatron/memory/freshness/curator.py`
- Create: `tests/unit/memory/freshness/test_monitor.py`
- Create: `tests/unit/memory/freshness/test_curator.py`

- [ ] **Step 1: TDD Monitor tests**

Cases: `valid_until <= now` → ARCHIVED, score 0.0; `superseded_by` resolves → SUPERSEDED, score 0.1; `updated_at` older than `freshness_stale_after_days` → STALE, score 0.25; otherwise unchanged.

- [ ] **Step 2: Implement Monitor**

Fetch record via `MemoryPostgresStore.get`, acquire lock `freshness:monitor:{record_id}`, heartbeat, apply rules in priority order (valid_until > superseded_by > stale), call `update_lifecycle(...)`, write checkpoint with new status.

- [ ] **Step 3: TDD Curator tests**

Cases: `status=CANDIDATE, evidence_count>=1` → `ACTIVE` + `auto_curated` tag appended; `status=ACTIVE` → idempotent (tag added once).

- [ ] **Step 4: Implement Curator**

Mirror Monitor skeleton. Call `MemoryPostgresStore.update` (existing — reuse tag update path) or a dedicated `update_lifecycle_and_tags` helper — keep tag path in the existing `update` method to avoid proliferation.

- [ ] **Step 5: Run tests** + commit.

```
pytest tests/unit/memory/freshness/test_monitor.py tests/unit/memory/freshness/test_curator.py -v
git add src/metatron/memory/freshness/monitor.py src/metatron/memory/freshness/curator.py tests/unit/memory/freshness/test_monitor.py tests/unit/memory/freshness/test_curator.py
git commit -m "feat(MTRNIX-304): FreshnessMonitor + Curator stages"
```

---

### Task 9: DecisionEngine

**Files:**
- Create: `src/metatron/memory/freshness/decision_engine.py`
- Create: `tests/unit/memory/freshness/test_decision_engine.py`

- [ ] **Step 1: TDD**

- `RuleBasedDecisionEngine.decide` returns confidence 0.55, keyword-extracted tags/entities.
- `LLMBackedDecisionEngine.decide` with mock provider returning valid JSON → `FreshnessDecision` with parsed fields.
- `LLMBackedDecisionEngine.decide` with malformed JSON → falls back to `RuleBasedDecisionEngine`.
- `apply_decision(record_id, decision)` — above-threshold: applies `action` (tag-add / mark_stale / ...); below-threshold: creates `ReviewEntry(reason="low_confidence_decision")`.

- [ ] **Step 2: Implement Protocol + two engines**

```python
class DecisionEngine(Protocol):
    async def decide(self, *, content: str, workspace_id: str, record_id: str) -> FreshnessDecision: ...

class RuleBasedDecisionEngine:
    async def decide(self, ...) -> FreshnessDecision:
        # keyword extraction, confidence=0.55, action="tag"

class LLMBackedDecisionEngine:
    def __init__(self, provider: LLMProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def decide(self, ...) -> FreshnessDecision:
        # Call provider via asyncio.to_thread (providers are sync)
        raw = await asyncio.to_thread(self._provider.chat, messages=[...], temperature=0.1)
        try:
            return _parse_decision(raw["content"])
        except (ValueError, KeyError):
            return await RuleBasedDecisionEngine().decide(...)


def build_default_decision_engine() -> DecisionEngine:
    settings = get_settings()
    if not settings.freshness_llm_api_base_url:
        return RuleBasedDecisionEngine()
    provider = create_provider(
        provider_name=settings.freshness_llm_provider or None,
        model=settings.freshness_llm_model,
        api_url=settings.freshness_llm_api_base_url,
        api_key=settings.freshness_llm_api_key,
    )
    return LLMBackedDecisionEngine(provider=provider, model=settings.freshness_llm_model)
```

- [ ] **Step 3: `apply_decision`**

Separate function `apply_decision(engine_out, record, pg_store, freshness_pg_store)`:
- If `decision.confidence >= threshold`: apply action (tag merge, verification_state update, etc.) via `pg_store.update_lifecycle` / `pg_store.update` (tags), emit `FRESHNESS_DECISION_APPLIED` event.
- Else: create `ReviewEntry(reason="low_confidence_decision", confidence=...)`, emit `FRESHNESS_REVIEW_CREATED`.

- [ ] **Step 4: Test + commit**

```
pytest tests/unit/memory/freshness/test_decision_engine.py -v
git add src/metatron/memory/freshness/decision_engine.py tests/unit/memory/freshness/test_decision_engine.py
git commit -m "feat(MTRNIX-304): DecisionEngine — rule-based + LLM-backed via llm/provider"
```

**Layer check:** `decision_engine.py` imports from `llm/` (L3 sibling — allowed) and calls the sync provider via `asyncio.to_thread` (consistent with the rest of the codebase).

---

### Task 10: Worker + metrics + entry-point

**Files:**
- Create: `src/metatron/memory/freshness/worker.py`
- Create: `src/metatron/memory/freshness/__main__.py`
- Create: `src/metatron/memory/freshness/metrics.py`
- Create: `tests/unit/memory/freshness/test_worker.py`

- [ ] **Step 1: Implement `metrics.py`**

Gate `prometheus_client` import with `try/except ImportError` → no-op stubs. (Phase A can ship without Prometheus — metrics are nice-to-have; structlog + MachineEvents carry the load.)

```python
try:
    from prometheus_client import Counter, Gauge, Histogram

    jobs_total = Counter("freshness_jobs_total", "Freshness jobs processed", ["status", "workspace_id"])
    queue_depth = Gauge("freshness_queue_depth", "Redis queue depth", ["workspace_id"])
    stage_duration = Histogram("freshness_stage_duration_seconds", "Per-stage duration", ["stage"])
    decision_confidence = Histogram("freshness_decision_confidence", "Decision confidence", buckets=[0.1,...,1.0])
    worker_errors = Counter("freshness_worker_errors_total", "Worker errors", ["stage"])
except ImportError:
    class _Noop:
        def labels(self, **_): return self
        def inc(self, *_): pass
        def observe(self, *_): pass
        def set(self, *_): pass
    jobs_total = queue_depth = stage_duration = decision_confidence = worker_errors = _Noop()
```

- [ ] **Step 2: TDD worker tests**

- `test_run_once_processes_batch` — given 3 jobs in a per-workspace queue, worker runs all 4 stages + DecisionEngine; emits MachineEvents; returns 3.
- `test_run_once_empty_queue_returns_zero`.
- `test_backoff_escalates_then_exits` — force three stage failures with a broken stage; assert backoff sleeps are 2s, 4s, 8s; after `freshness_max_consecutive_errors` failures, worker re-raises.
- `test_flag_off_exits_immediately` — `freshness_enabled=False` → `main()` returns 0 without polling.

- [ ] **Step 3: Implement `FreshnessWorker`**

```python
class FreshnessWorker:
    def __init__(
        self,
        *,
        coordination: CoordinationStore,
        memory_service_factory: Callable[[str], Awaitable[MemoryService]],
        freshness_pg: FreshnessPostgresStore,
        decision_engine: DecisionEngine,
    ) -> None: ...

    async def run_once(self, max_jobs: int) -> int:
        processed = 0
        workspace_ids = await self.coordination.list_active_workspaces()
        for ws in workspace_ids:
            jobs = await self.coordination.dequeue_batch(ws, max_items=max_jobs)
            for job in jobs:
                await self._process(job)
                processed += 1
        return processed

    async def _process(self, job: FreshnessJob) -> None:
        # save freshness_job_received MachineEvent
        # Linker → Reconciler → Monitor → Curator → DecisionEngine → apply_decision
        # save freshness_job_processed MachineEvent
        ...
```

- [ ] **Step 4: Implement `main()` + `__main__.py`**

`worker.py:main()`:
```python
async def main() -> None:
    configure_logging(...)
    settings = get_settings()
    if not settings.freshness_enabled:
        logger.info("freshness.disabled.exit")
        return
    # bootstrap Redis, PG engine, CoordinationStore, FreshnessPostgresStore, decision_engine
    # memory_service_factory = lambda ws: build_memory_service_for_workspace(ws)  # reuse mcp.tools._memory_deps
    worker = FreshnessWorker(...)
    consecutive_errors = 0
    while True:
        try:
            processed = await worker.run_once(settings.freshness_max_jobs_per_iteration)
            consecutive_errors = 0
            if processed == 0:
                await asyncio.sleep(settings.freshness_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            consecutive_errors += 1
            backoff = min(
                settings.freshness_backoff_base_seconds * (2 ** (consecutive_errors - 1)),
                settings.freshness_backoff_max_seconds,
            )
            logger.error("freshness.worker.iteration_failed", attempt=consecutive_errors, backoff=backoff, exc_info=True)
            if consecutive_errors >= settings.freshness_max_consecutive_errors:
                logger.critical("freshness.worker.hard_exit", errors=consecutive_errors)
                raise
            await asyncio.sleep(backoff)
```

`__main__.py`:
```python
import asyncio
from metatron.memory.freshness.worker import main

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: Test + commit**

```
pytest tests/unit/memory/freshness/test_worker.py -v
git add src/metatron/memory/freshness/worker.py src/metatron/memory/freshness/__main__.py src/metatron/memory/freshness/metrics.py tests/unit/memory/freshness/test_worker.py
git commit -m "feat(MTRNIX-304): freshness worker entry-point with bounded loop + backoff"
```

**Smoke test:**
```
METATRON_FRESHNESS_ENABLED=false python -m metatron.memory.freshness
# expected: logs "freshness.disabled.exit" and returns

METATRON_FRESHNESS_ENABLED=true python -m metatron.memory.freshness
# expected: logs "freshness.worker.started", polls empty queue every 2s, Ctrl-C exits cleanly
```

---

### Task 11: Integration tests

**Files:**
- Create: `tests/integration/memory/__init__.py`
- Create: `tests/integration/memory/freshness/__init__.py`
- Create: `tests/integration/memory/freshness/test_end_to_end.py`
- Create: `tests/integration/memory/freshness/test_reconciler_qdrant.py`

- [ ] **Step 1: End-to-end test**

Setup: `freshness_enabled=True`, live PG + Qdrant + Redis + Neo4j (per CLAUDE.md, services are assumed running). Flow:
1. `memory_store` a record → verify job lands in `freshness:queue:{ws}` via Redis MCP client.
2. Run `await worker.run_once(1)`.
3. Assert PG: `memory_records.status` transitions, `evidence_count` non-zero, appropriate MachineEvent rows.
4. Assert Qdrant payload updated (`status`, `freshness_score`).
5. Assert Neo4j `LINKED_TO` edges (if expected).

- [ ] **Step 2: Reconciler duplicate test**

Store two records with identical content → second triggers `ReviewEntry`. Assert row in `review_entries`, ALIAS edge in Neo4j.

- [ ] **Step 3: Run**

```
make test-all
# integration tests run, require live services
```

- [ ] **Step 4: Commit**

```
git add tests/integration/memory/
git commit -m "test(MTRNIX-304): integration tests — e2e freshness pipeline + reconciler"
```

---

### Task 12: Docker compose + docs

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docs/superpowers/plans/2026-04-20-freshness-worker-agent-memory.md` (this file)

- [ ] **Step 1: Add optional `freshness-worker` service**

```yaml
  freshness-worker:
    profiles: ["freshness"]
    build: .
    command: python -m metatron.memory.freshness
    environment:
      METATRON_FRESHNESS_ENABLED: "true"
      # ... inherits DB connection vars from `.env`
    depends_on:
      - postgres
      - qdrant
      - neo4j
      - redis
    restart: unless-stopped
```

Running `docker compose --profile freshness up -d` starts the worker; default `docker compose up -d` does NOT.

- [ ] **Step 2: Do NOT extend `CLAUDE.md` yet** — that is the `documenter` teammate's job post-approval.

- [ ] **Step 3: Commit**

```
git add docker-compose.yml
git commit -m "chore(MTRNIX-304): docker-compose optional freshness-worker service"
```

---

### Task 13: Final verification

- [ ] **Step 1:** `make lint`
- [ ] **Step 2:** `make typecheck`
- [ ] **Step 3:** `make test`
- [ ] **Step 4:** `make test-all` (integration)
- [ ] **Step 5:** `make migrate` dry-run: `alembic upgrade head --sql | head -100` and `alembic downgrade -1 && alembic upgrade head`
- [ ] **Step 6:** Smoke — `METATRON_FRESHNESS_ENABLED=false python -m metatron.memory.freshness` returns immediately; `=true` enters poll loop; Ctrl-C exits cleanly.
- [ ] **Step 7:** Backward-compat smoke — run existing `tests/unit/test_memory_store.py`, `test_memory_batch_store.py`, `test_memory_update.py`, `test_memory_search.py` — all pass with flag OFF.

---

## Acceptance Criteria (reviewer checklist)

1. `make lint` — zero errors on new files and all modified files.
2. `make typecheck` — zero errors (mypy strict).
3. `make test` — all new unit tests pass + no regression on existing ~1150 tests.
4. `make test-all` — integration suite including new `tests/integration/memory/freshness/*` passes against live PG + Qdrant + Neo4j + Redis.
5. `make migrate` runs cleanly on an empty DB; `alembic downgrade -1 && alembic upgrade head` round-trips.
6. `METATRON_FRESHNESS_ENABLED=false` (default): `memory_store` / `memory_batch_store` / `memory_update` / `memory_search` / REST `/api/v1/memory/*` behaviour is byte-identical to pre-branch; no Redis traffic attributable to freshness.
7. `METATRON_FRESHNESS_ENABLED=true` + `python -m metatron.memory.freshness` processes a single enqueued job end-to-end (verified by integration test).
8. Every PG query, Redis key, and Qdrant filter in new code carries `workspace_id`. Reviewer grep: `grep -rn "workspace_id" src/metatron/memory/freshness/` should hit every file that reads/writes data.
9. No new import from `agent/`, `channels/`, `api/` into `memory/freshness/`.
10. `interfaces.py` is not modified. `core/events.py` adds 4 new event names; existing names untouched.

---

## Concerns flagged for the team lead

1. **Enterprise coordination:** `core/events.py` gains 4 new event names (`FRESHNESS_JOB_ENQUEUED`, `FRESHNESS_JOB_PROCESSED`, `FRESHNESS_DECISION_APPLIED`, `FRESHNESS_REVIEW_CREATED`). The enterprise repo's audit / Control Center plugin will likely want to subscribe to at least the latter two. Not a breaking change, but worth a heads-up before merge.
2. **`prometheus_client` dependency:** the spec calls for Prometheus metrics but the package is not listed in `pyproject.toml`'s runtime deps as far as I could see. Plan step 10.1 gates it behind `try/except ImportError` so the worker runs either way. **Decision requested:** either add `prometheus-client` to `pyproject.toml` in this ticket (preferred if the metrics are considered part of the DoD), or explicitly scope metrics out to a follow-up.
3. **Redis client extension scope:** `storage/redis.py` currently wraps only `get/set/delete/exists`. This plan adds 9 methods including Lua-scripted token-guarded locks. That is a legitimate storage-layer extension (no business logic), but it's a meaningful surface increase — worth a reviewer eye on the `acquire_lock` / `release_lock` Lua scripts to avoid the classic "release someone else's lock" bug.
4. **Interfaces.py abstention:** I chose NOT to introduce a `DecisionEngine` ABC in `core/interfaces.py` for Phase A. The spec allows this (protocol stays local to `memory/freshness/`). If Phase B (MTRNIX-313) ports the same pipeline to KB, we promote the protocol to `interfaces.py` then — at that point both call-sites exist and the shape is concrete. This is deliberate avoidance of premature abstraction; flagging it here so the reviewer does not ask.
5. **Output constraint violation:** my runtime is in read-only mode and I could not create the plan file at `docs/superpowers/plans/2026-04-20-freshness-worker-agent-memory.md` nor run the requested `git commit`. The full plan is delivered as this assistant message. A coder subagent (or the team lead) with write permissions should persist this content verbatim to the target path and commit with message `docs(MTRNIX-304): implementation plan`.

### Critical Files for Implementation

- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/core/models.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/migrations/versions/016_freshness_lifecycle.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/memory/freshness/worker.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/memory/freshness/coordination.py`
- `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/src/metatron/storage/redis.py`

---

## Compact summary (to the team lead)

**(a) Plan file path (intended):** `/Users/sm/Projects/metatron/metatron_mvp/metatroncore/docs/superpowers/plans/2026-04-20-freshness-worker-agent-memory.md` — **NOT written to disk** because my runtime is in read-only planning mode. Full content is in this message; a coder subagent or the lead needs to persist and commit it (`docs(MTRNIX-304): implementation plan`).

**(b) Subtasks:** 13 ordered tasks, each with file list, TDD steps where relevant, and an explicit commit at the end. Step order: models → migration → storage → config/events → coordination → producer → Linker/Reconciler → Monitor/Curator → DecisionEngine → worker+metrics → integration tests → docker compose → final verification.

**(c) Concerns flagged:**
1. 4 new event constants in `core/events.py` — enterprise plugin coordination before merge (not breaking).
2. `prometheus-client` is not currently a runtime dep; plan gates it behind `try/except ImportError` but the lead should confirm whether to add it as a real dep in this ticket or scope metrics out.
3. `storage/redis.py` grows by 9 methods including Lua-scripted locks — request a careful reviewer pass on the token-guarded `release_lock` / `heartbeat_lock` Lua scripts.
4. No `core/interfaces.py` changes in Phase A — deliberate deferral. Promote `DecisionEngine` Protocol only when MTRNIX-313 adds a second call site.
5. Read-only execution mode prevented writing the file and committing per the original instruction — lead or coder must do that step manually.