# Memory MCP: lifecycle-status filter + review queue tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `status` lifecycle filter to existing `metatron_memory_search` / `metatron_memory_list` MCP tools and introduce two new MCP tools `metatron_memory_review_list` / `metatron_memory_review_resolve` that let external agents interact with the review queue written by the freshness pipeline (MTRNIX-304 Phase A / MTRNIX-313 Phase B).

**Architecture:** Filter is push-down at every layer (Qdrant payload, PG WHERE, graph-leg batched PG lookup). Review tools go through `MemoryService` — no direct `FreshnessStore` usage in MCP code. `memory_review_resolve` is a soft-transition tool (no hard DELETE): `keep → ACTIVE`, `archive → ARCHIVED`, `merge_into:<id> → SUPERSEDED`, `discard → ARCHIVED`. One new `FRESHNESS_REVIEW_RESOLVED` event constant. One new `status` field on the `MemoryRecordDTO` Pydantic model. No migration. No flag.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy async (asyncpg), `redis.asyncio`, `AsyncQdrantClient`, FastMCP, structlog, pytest (`asyncio_mode = "auto"`).

**Jira:** MTRNIX-314
**Depends on:** MTRNIX-304 (merged, PR #83), MTRNIX-313 (merged, PR #85).
**Spec:** `docs/superpowers/specs/2026-04-22-memory-mcp-lifecycle-status-and-review-queue-design.md`
**Branch:** `feature/MTRNIX-314` (already checked out).

---

## Layer Boundary Summary

| File | Layer | Allowed imports |
|---|---|---|
| `core/events.py` (extend) | L0 | stdlib |
| `storage/memory_postgres.py` (extend) | L1 | SQLAlchemy async |
| `storage/memory_qdrant.py` (extend) | L1 | `AsyncQdrantClient` |
| `storage/freshness_pg.py` (extend) | L1 | SQLAlchemy async |
| `memory/search.py` (extend) | L3 | `core.*`, `storage.*` |
| `memory/service.py` (extend) | L3 | `core.*`, `storage.*` |
| `mcp/tools/models.py` (extend) | L3 | pydantic |
| `mcp/tools/memory_search.py` (extend) | L3 | `mcp.*`, `memory.service` |
| `mcp/tools/memory_list.py` (extend) | L3 | `mcp.*`, `memory.service` |
| `mcp/tools/memory_review_list.py` (new) | L3 | `mcp.*`, `memory.service` |
| `mcp/tools/memory_review_resolve.py` (new) | L3 | `mcp.*`, `memory.service` |
| `mcp/tools/__init__.py` (extend) | L3 | side-effect imports |
| `mcp/tools/_memory_deps.py` (extend) | L3 | `storage.freshness_pg`, `memory.service` |
| `mcp/tools/_memory_utils.py` (extend) | L3 | `core.models` |

**Not touched:** `agent/`, `channels/`, `api/routes/chat.py`, `api/routes/finops.py`, `skills/`, `core/interfaces.py`, `core/config.py`, `workspaces/`, `freshness/*` (Phase A/B code stays as-is).

**No upward imports.** MCP tools (L3) import from `memory/` (L3) and `mcp/` (L3); never from `api/`, `agent/`, `channels/`.

---

## Config Vars

**None added.** Filter/review tools are always-on; behaviour is opt-in via parameters.

---

## Event Constants

**One new constant.** `FRESHNESS_REVIEW_RESOLVED = "freshness_review_resolved"` added to `src/metatron/core/events.py`.

Payload convention (documented inline in `core/events.py`):

```
freshness_review_resolved -> {
    "workspace_id", "target_kind", "target_id", "review_entry_id",
    "action", "old_status", "new_status"
}
```

**ENTERPRISE COORDINATION COURTESY:** the PR description must mention the new event constant — subscribers who want to act on resolution (e.g. replicate to CC audit log) can subscribe to it. Non-breaking.

---

## Backward Compatibility Guarantee

- Existing callers of `memory_search` / `memory_list` that do not pass `status` see behaviour `default=["active"]`. For deployments where the freshness worker has never run, all rows are `active` in PG (server default), so the filter is a no-op in practice. `status=["all"]` restores pre-ticket semantics.
- `MemoryService(freshness_store=None)` works for legacy construction paths; the new `list_review_entries` / `resolve_review` methods raise `RuntimeError` when called without the dep wired.
- No DB migration.
- Phase A (MTRNIX-304) + Phase B (MTRNIX-313) tests stay green.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Modify | `src/metatron/core/events.py` | Add `FRESHNESS_REVIEW_RESOLVED` constant + payload docstring. |
| Modify | `src/metatron/storage/memory_postgres.py` | `list_records` + `count_records` gain `status: list[LifecycleStatus] \| None`. New helper `get_many_statuses(workspace_id, record_ids) -> dict[str, LifecycleStatus]`. |
| Modify | `src/metatron/storage/memory_qdrant.py` | `upsert` writes `"status"` payload. `search` gains `status_exclude: list[str] \| None`. |
| Modify | `src/metatron/storage/freshness_pg.py` | `list_review_entries` gains `offset=`, `reason=`. New `count_review_entries(...) -> int`. New `delete_review_entry(workspace_id, id) -> bool`. |
| Modify | `src/metatron/memory/search.py` | `hybrid_search` gains `status_filter: list[LifecycleStatus] \| None`. Graph-leg batched PG lookup drops excluded statuses. Session leg untouched. |
| Modify | `src/metatron/memory/service.py` | Constructor gains optional `freshness_store: FreshnessStore \| None`. New `list_review_entries(...) -> (list, total)`. New `resolve_review(...) -> ReviewResolution`. `search()` passes `status_filter` through. |
| Create | `src/metatron/memory/resolution.py` | New tiny module with `ReviewResolution` dataclass (return type for `resolve_review`). |
| Modify | `src/metatron/mcp/tools/_memory_deps.py` | Wire `FreshnessStore` into `MemoryService`. |
| Modify | `src/metatron/mcp/tools/_memory_utils.py` | New `parse_status_filter(status: list[str] \| None) -> list[LifecycleStatus] \| None` helper. `"all"` short-circuits to `None`. |
| Modify | `src/metatron/mcp/tools/models.py` | Add `status` field on `MemoryRecordDTO`. New `ReviewEntryDTO`, `MemoryReviewListResponse`, `MemoryReviewResolveResponse` models. |
| Modify | `src/metatron/mcp/tools/memory_search.py` | Add `status` param; parse + pass through. |
| Modify | `src/metatron/mcp/tools/memory_list.py` | Add `status` param; push down into PG. |
| Create | `src/metatron/mcp/tools/memory_review_list.py` | New tool. |
| Create | `src/metatron/mcp/tools/memory_review_resolve.py` | New tool. |
| Modify | `src/metatron/mcp/tools/__init__.py` | Side-effect imports of the two new tool modules. |
| Create | `tests/unit/mcp/tools/test_memory_search_status_filter.py` | Default + all + include-set + invalid-enum cases. |
| Create | `tests/unit/mcp/tools/test_memory_list_status_filter.py` | PG push-down mocked. |
| Create | `tests/unit/mcp/tools/test_memory_review_list.py` | Paging + filters + error paths. |
| Create | `tests/unit/mcp/tools/test_memory_review_resolve.py` | 4 actions + idempotency + error paths. |
| Create | `tests/unit/memory/test_service_review.py` | Service-layer review methods. |
| Create | `tests/unit/memory/test_search_status_pushdown.py` | Hybrid-search graph-leg + Qdrant filter + session-leg. |
| Create | `tests/unit/storage/test_memory_postgres_list_status.py` | `list_records(status=)` + `count_records(status=)` + `get_many_statuses`. |
| Create | `tests/unit/storage/test_memory_qdrant_status_payload.py` | `upsert` payload + `search(status_exclude=)` filter shape. |
| Create | `tests/unit/storage/test_freshness_pg_review_extensions.py` | `list_review_entries(offset=, reason=)` + `count_review_entries` + `delete_review_entry`. |
| Create | `tests/integration/mcp/test_memory_review_end_to_end.py` | Live PG+Qdrant+Redis end-to-end. |
| Create | `tests/integration/mcp/test_memory_search_status_live.py` | Live Qdrant filter verification. |
| Create | `scripts/backfill_memory_qdrant_status_payload.py` | Optional one-shot backfill. |
| Modify | `docs/MCP_API.md` | Document 2 new tools + `status` param on search/list + enum values table. |
| Modify | `src/metatron/mcp/.claude/claude.md` | List new tool files + description. |
| Modify | `src/metatron/memory/.claude/CLAUDE.md` | Mention `list_review_entries` / `resolve_review` service methods. |
| Modify | `src/metatron/storage/.claude/claude.md` | Mention `list_records(status=)`, Qdrant `status` payload, `FreshnessStore` additions. |
| Modify | `CHANGELOG.md` | One-line entry. |

---

## Ordered Tasks

Execute in order. After **every** task, run `make lint && make typecheck && make test` as separate commands (never chain with `&&` on the user's request). TDD — write the test first where the task spec says "Step 1: Write test".

---

### Task 1: Event constant

**Files:** `src/metatron/core/events.py`

- [ ] **Step 1: Add the constant + docstring.**
  Append after `FRESHNESS_REVIEW_CREATED`:
  ```python
  #   freshness_review_resolved  -> {"workspace_id", "target_kind", "target_id",
  #                                  "review_entry_id", "action",
  #                                  "old_status", "new_status"}
  FRESHNESS_REVIEW_RESOLVED = "freshness_review_resolved"
  ```
- [ ] **Step 2: Run tests.** `make test`
- [ ] **Step 3: Commit.**
  ```
  git add src/metatron/core/events.py
  git commit -m "feat(MTRNIX-314): add FRESHNESS_REVIEW_RESOLVED event constant"
  ```

**Acceptance:** Constant importable; docstring payload convention matches spec.

---

### Task 2: `FreshnessStore` review-queue extensions

**Files:**
- Modify: `src/metatron/storage/freshness_pg.py`
- Create: `tests/unit/storage/test_freshness_pg_review_extensions.py`

- [ ] **Step 1: Write tests first.**
  Tests for:
  - `list_review_entries(offset=5, limit=10)` returns the second page.
  - `list_review_entries(reason="possible_duplicate")` filters on reason.
  - `count_review_entries(workspace_id, target_kind="memory_record", reason="possible_duplicate")` returns the correct count.
  - `delete_review_entry(workspace_id, entry_id)` returns `True` once, `False` on re-delete.
  - `delete_review_entry` with wrong workspace → `False` (workspace isolation).

- [ ] **Step 2: Extend `list_review_entries`.**
  Add `offset: int = 0` and `reason: str | None = None` keyword args. Extend WHERE clause + `OFFSET :offset`.

- [ ] **Step 3: Add `count_review_entries`.**
  ```python
  async def count_review_entries(
      self,
      workspace_id: str,
      *,
      target_kind: str | None = None,
      target_id: str | None = None,
      record_id: str | None = None,
      reason: str | None = None,
  ) -> int:
      ...
  ```
  Same WHERE construction pattern as `list_review_entries`.

- [ ] **Step 4: Add `delete_review_entry`.**
  ```python
  async def delete_review_entry(
      self, workspace_id: str, review_id: str
  ) -> bool:
      async with self._engine.begin() as conn:
          result = await conn.execute(
              text(
                  "DELETE FROM review_entries "
                  "WHERE id = :id AND workspace_id = :ws"
              ),
              {"id": review_id, "ws": workspace_id},
          )
          return result.rowcount > 0
  ```

- [ ] **Step 5: Run tests + lint + typecheck.** Each as a separate command.
- [ ] **Step 6: Commit.**
  ```
  git add src/metatron/storage/freshness_pg.py tests/unit/storage/test_freshness_pg_review_extensions.py
  git commit -m "feat(MTRNIX-314): FreshnessStore offset/reason filters + delete_review_entry"
  ```

**Acceptance:** 5+ new unit tests green. Workspace isolation enforced on delete.

---

### Task 3: `MemoryPostgresStore` status filter + `get_many_statuses`

**Files:**
- Modify: `src/metatron/storage/memory_postgres.py`
- Create: `tests/unit/storage/test_memory_postgres_list_status.py`

- [ ] **Step 1: Write tests first.**
  - `list_records(status=[LifecycleStatus.ACTIVE])` returns only ACTIVE.
  - `list_records(status=[LifecycleStatus.ACTIVE, LifecycleStatus.CANDIDATE])` returns ACTIVE + CANDIDATE.
  - `list_records(status=None)` returns all (unchanged behaviour).
  - `count_records(status=[...])` matches `len(list_records(...))` over an in-memory fixture.
  - `get_many_statuses(ws, ["id1","id2","id3"])` returns `{"id1": ACTIVE, "id2": STALE}` (missing id3 → absent from dict; not in dict means not-found).

- [ ] **Step 2: Extend `list_records`.**
  Add parameter:
  ```python
  status: list[LifecycleStatus] | None = None,
  ```
  When present, add:
  ```python
  where_parts.append("status = ANY(:status_list)")
  params["status_list"] = [s.value for s in status]
  ```

- [ ] **Step 3: Extend `count_records`** with the same parameter / WHERE extension.

- [ ] **Step 4: Add `get_many_statuses`.**
  ```python
  async def get_many_statuses(
      self, workspace_id: str, record_ids: list[str]
  ) -> dict[str, LifecycleStatus]:
      if not record_ids:
          return {}
      async with self._engine.begin() as conn:
          result = await conn.execute(
              text(
                  "SELECT id, status FROM memory_records "
                  "WHERE workspace_id = :ws AND id = ANY(:ids)"
              ),
              {"ws": workspace_id, "ids": list(record_ids)},
          )
          rows = result.fetchall()
      out: dict[str, LifecycleStatus] = {}
      for r in rows:
          try:
              out[r[0]] = LifecycleStatus(r[1])
          except ValueError:
              out[r[0]] = LifecycleStatus.ACTIVE
      return out
  ```

- [ ] **Step 5: Update top-of-file import** to use `LifecycleStatus` alongside `MemoryStatus` (they're the same; new code should prefer `LifecycleStatus`).

- [ ] **Step 6: Run tests + lint + typecheck.**
- [ ] **Step 7: Commit.**
  ```
  git add src/metatron/storage/memory_postgres.py tests/unit/storage/test_memory_postgres_list_status.py
  git commit -m "feat(MTRNIX-314): list_records/count_records status filter + get_many_statuses"
  ```

**Acceptance:** 5 new unit tests green. Phase A regression tests still green.

---

### Task 4: `MemoryQdrantStore` status payload + exclude filter

**Files:**
- Modify: `src/metatron/storage/memory_qdrant.py`
- Create: `tests/unit/storage/test_memory_qdrant_status_payload.py`

- [ ] **Step 1: Write tests first** (mock `AsyncQdrantClient`).
  - `upsert(record)` writes `"status": record.status.value` in the payload kwarg.
  - `search(..., status_exclude=["archived","superseded"])` builds `Filter(must_not=[FieldCondition(key="status", match=MatchAny(any=["archived","superseded"]))])` or equivalent, AND-combined with the existing agent_id/scope `must` clauses.
  - `search(status_exclude=None)` leaves the filter shape unchanged.
  - `search(status_exclude=[])` — no-op, same as None.

- [ ] **Step 2: Extend `upsert`** payload dict:
  ```python
  "status": record.status.value,
  ```

- [ ] **Step 3: Extend `search` signature** with `status_exclude: list[str] | None = None`. Build a `must_not` list of `FieldCondition` entries. Combine with existing `must` via a single `Filter(must=..., must_not=...)`.

- [ ] **Step 4: Run tests + lint + typecheck.**
- [ ] **Step 5: Commit.**
  ```
  git add src/metatron/storage/memory_qdrant.py tests/unit/storage/test_memory_qdrant_status_payload.py
  git commit -m "feat(MTRNIX-314): memory Qdrant carries status payload + search exclude filter"
  ```

**Acceptance:** Tests green. No change to search latency for default (status_exclude None).

---

### Task 5: Backfill script (optional but included in PR)

**Files:** `scripts/backfill_memory_qdrant_status_payload.py`

- [ ] **Step 1: Write script.**
  Iterates over every `memory_records` row in a given workspace, pulls `id + status`, calls `MemoryQdrantStore.update_payload(record_id, {"status": status.value})` in batches. Idempotent (re-running is safe). CLI flags: `--workspace-id`, `--batch-size` (default 200), `--dry-run`.

- [ ] **Step 2: Manual smoke test** on a dev workspace. Not part of CI.

- [ ] **Step 3: Commit.**
  ```
  git add scripts/backfill_memory_qdrant_status_payload.py
  git commit -m "feat(MTRNIX-314): backfill script for memory Qdrant status payload"
  ```

**Acceptance:** Running on a seeded workspace sets `status` payload on all existing points. No-op second run.

---

### Task 6: `MemorySearchService` status push-down

**Files:**
- Modify: `src/metatron/memory/search.py`
- Create: `tests/unit/memory/test_search_status_pushdown.py`

- [ ] **Step 1: Write tests first.**
  - `hybrid_search(status_filter=[LifecycleStatus.ACTIVE])` → `qdrant.search` called with `status_exclude=[<all enum values minus "active">]`.
  - Graph-only hit with `status=ARCHIVED` (via `get_many_statuses`) dropped from merged dict before ranking.
  - Session-leg records never filtered out.
  - `hybrid_search(status_filter=None)` → `qdrant.search` called with `status_exclude=None`.

- [ ] **Step 2: Add helper** in the same file or a new tiny file `memory/status_filter.py`:
  ```python
  def compute_exclude_set(
      status_filter: list[LifecycleStatus] | None,
  ) -> list[str] | None:
      if status_filter is None:
          return None
      include = {s.value for s in status_filter}
      return [s.value for s in LifecycleStatus if s.value not in include]
  ```

- [ ] **Step 3: Extend `hybrid_search` signature** with `status_filter: list[LifecycleStatus] | None = None`. Pass `compute_exclude_set(status_filter)` to `qdrant.search`.

- [ ] **Step 4: After leg fan-in, before blend**, run:
  ```python
  if status_filter is not None:
      graph_only_ids = [
          rid for rid, res in merged.items()
          if rid not in raw_dense and rid not in session_lookup
      ]
      if graph_only_ids:
          statuses = await pg_store.get_many_statuses(workspace_id, graph_only_ids)
          allowed = set(s.value for s in status_filter)
          for rid in graph_only_ids:
              if statuses.get(rid, LifecycleStatus.ACTIVE).value not in allowed:
                  merged.pop(rid, None)
  ```
  Plumb `pg_store` in via constructor: `MemorySearchService` grows a new `pg_store: MemoryPostgresStore | None = None` kwarg; when None, graph-leg post-filter is skipped (safe default).

- [ ] **Step 5: Run tests + lint + typecheck.**
- [ ] **Step 6: Commit.**
  ```
  git add src/metatron/memory/search.py tests/unit/memory/test_search_status_pushdown.py
  git commit -m "feat(MTRNIX-314): MemorySearchService status filter push-down"
  ```

**Acceptance:** Graph-only ARCHIVED hits dropped; session hits preserved; Qdrant exclude filter applied.

---

### Task 7: `MemoryService` review methods + status plumbing

**Files:**
- Create: `src/metatron/memory/resolution.py`
- Modify: `src/metatron/memory/service.py`
- Create: `tests/unit/memory/test_service_review.py`

- [ ] **Step 1: Create `resolution.py`:**
  ```python
  from __future__ import annotations
  from dataclasses import dataclass

  @dataclass(frozen=True)
  class ReviewResolution:
      review_id: str
      target_id: str
      action: str
      old_status: str
      new_status: str
      superseded_by: str | None
      machine_event_id: str
  ```

- [ ] **Step 2: Write service tests first.**
  - `list_review_entries` delegates to `FreshnessStore` with the right args, returns `(entries, total)`.
  - `resolve_review(action="keep")`: PG lifecycle update to ACTIVE, review entry delete, MachineEvent append, EventBus emit (all verified on mocks; order: PG write → review delete → event → bus).
  - `resolve_review(action="merge_into:<id>")`: validates target exists; SUPERSEDED + `superseded_by`.
  - `resolve_review(action="merge_into:<nonexistent>")`: raises `ValueError` (MCP tool converts to `INVALID_PARAMS`).
  - `resolve_review(action="discard")`: status → ARCHIVED, `verification_state="discarded_via_review"`.
  - `resolve_review` with review not found → raises `MemoryNotFoundError` (reuse existing exception).
  - `resolve_review` without `freshness_store` wired → `RuntimeError`.

- [ ] **Step 3: Extend `MemoryService.__init__`** with:
  ```python
  freshness_store: FreshnessStore | None = None,
  event_bus: EventBus | None = None,
  ```
  Store as private attrs.

- [ ] **Step 4: Add `list_review_entries`:**
  ```python
  async def list_review_entries(
      self,
      workspace_id: str,
      *,
      record_id: str | None = None,
      reason: str | None = None,
      limit: int = 20,
      offset: int = 0,
  ) -> tuple[list[ReviewEntry], int]:
      self._check_workspace(workspace_id)
      if self._freshness_store is None:
          raise RuntimeError("freshness_store not configured")
      entries = await self._freshness_store.list_review_entries(
          workspace_id,
          target_kind="memory_record",
          record_id=record_id,
          reason=reason,
          limit=limit,
          offset=offset,
      )
      total = await self._freshness_store.count_review_entries(
          workspace_id,
          target_kind="memory_record",
          record_id=record_id,
          reason=reason,
      )
      return entries, total
  ```

- [ ] **Step 5: Add `resolve_review`:**
  Implementation sketch:
  ```python
  async def resolve_review(
      self,
      workspace_id: str,
      *,
      review_id: str,
      action: str,
      notes: str | None = None,
      actor: str = "mcp_caller",
  ) -> ReviewResolution:
      self._check_workspace(workspace_id)
      if self._freshness_store is None:
          raise RuntimeError("freshness_store not configured")

      # Parse action
      action_kind, merge_target = _parse_action(action)   # helper in resolution.py

      # Load review entry
      entries = await self._freshness_store.list_review_entries(
          workspace_id, target_kind="memory_record", limit=1000,
      )
      entry = next((e for e in entries if e.id == review_id), None)
      if entry is None:
          raise MemoryNotFoundError(f"Review entry {review_id} not found")

      # Load record + validate merge target
      record = await self._pg.get(workspace_id, entry.target_id)
      if record is None:
          raise MemoryNotFoundError(f"Record {entry.target_id} not found")
      old_status = record.status.value

      if action_kind == "merge_into":
          target_rec = await self._pg.get(workspace_id, merge_target)
          if target_rec is None:
              raise ValueError(f"merge_into target {merge_target} not found")
          new_status = LifecycleStatus.SUPERSEDED
          verification_state = "merged_via_review"
          superseded_by = merge_target
      elif action_kind == "keep":
          new_status = LifecycleStatus.ACTIVE
          verification_state = "keep_resolved"
          superseded_by = None
      elif action_kind == "archive":
          new_status = LifecycleStatus.ARCHIVED
          verification_state = "archived_via_review"
          superseded_by = None
      elif action_kind == "discard":
          new_status = LifecycleStatus.ARCHIVED
          verification_state = "discarded_via_review"
          superseded_by = None
      else:
          raise ValueError(f"Unknown action: {action}")

      # Transition
      await self._pg.update_lifecycle(
          workspace_id, entry.target_id,
          status=new_status,
          verification_state=verification_state,
          superseded_by=superseded_by,
      )
      # Delete review entry
      await self._freshness_store.delete_review_entry(workspace_id, review_id)

      # MachineEvent
      evt = MachineEvent(
          workspace_id=workspace_id,
          event_type="freshness_review_resolved",
          actor=actor,
          target_kind="memory_record",
          target_id=entry.target_id,
          payload={
              "review_entry_id": review_id,
              "action": action_kind,
              "merge_into_target_id": merge_target,
              "old_status": old_status,
              "new_status": new_status.value,
              "superseded_by": superseded_by,
              "notes": (notes or "")[:1024],
          },
      )
      saved_evt = await self._freshness_store.save_machine_event(evt)

      # Best-effort Qdrant payload sync
      try:
          await self._qdrant.update_payload(
              entry.target_id, {"status": new_status.value}
          )
      except Exception:
          logger.warning(
              "memory_service.review_resolve.qdrant_sync_failed",
              record_id=entry.target_id, exc_info=True,
          )

      # EventBus
      if self._event_bus is not None:
          try:
              await self._event_bus.emit(
                  FRESHNESS_REVIEW_RESOLVED,
                  {
                      "workspace_id": workspace_id,
                      "target_kind": "memory_record",
                      "target_id": entry.target_id,
                      "review_entry_id": review_id,
                      "action": action_kind,
                      "old_status": old_status,
                      "new_status": new_status.value,
                  },
              )
          except Exception:
              logger.warning(
                  "memory_service.review_resolve.bus_emit_failed",
                  exc_info=True,
              )

      return ReviewResolution(
          review_id=review_id,
          target_id=entry.target_id,
          action=action_kind,
          old_status=old_status,
          new_status=new_status.value,
          superseded_by=superseded_by,
          machine_event_id=saved_evt.id,
      )
  ```

- [ ] **Step 6: Pass `status_filter` through `search()`** on `MemoryService` → `MemorySearchService.hybrid_search`. Add `status_filter: list[LifecycleStatus] | None = None` kwarg on `MemoryService.search`.

- [ ] **Step 7: Add `_parse_action` helper** in `resolution.py`:
  ```python
  def _parse_action(action: str) -> tuple[str, str | None]:
      if action in ("keep", "archive", "discard"):
          return action, None
      if action.startswith("merge_into:"):
          target = action.removeprefix("merge_into:").strip()
          if not target:
              raise ValueError("merge_into: requires a target record id")
          return "merge_into", target
      raise ValueError(f"Unknown action: {action}")
  ```

- [ ] **Step 8: Run tests + lint + typecheck.**
- [ ] **Step 9: Commit.**
  ```
  git add src/metatron/memory/resolution.py src/metatron/memory/service.py tests/unit/memory/test_service_review.py
  git commit -m "feat(MTRNIX-314): MemoryService review list/resolve + status_filter plumbing"
  ```

**Acceptance:** 7+ service tests green. Atomicity: lifecycle + review-delete + event in the same logical transaction (one PG connection context).

---

### Task 8: `_memory_deps` wires `FreshnessStore` + `pg_store` into search

**Files:** `src/metatron/mcp/tools/_memory_deps.py`

- [ ] **Step 1: Extend `build_memory_service_for_workspace`.**
  After `pg_store = MemoryPostgresStore(engine)`:
  ```python
  from metatron.storage.freshness_pg import FreshnessStore
  freshness_store = FreshnessStore(engine)
  ```
  After `search = MemorySearchService(qdrant=qdrant_store, redis=redis_cache)`:
  ```python
  search = MemorySearchService(
      qdrant=qdrant_store, redis=redis_cache, pg_store=pg_store,
  )
  ```
  Pass `freshness_store=freshness_store` into `MemoryService(...)`.

- [ ] **Step 2: EventBus.**
  MCP tools run outside FastAPI request scope and do not have a `PluginManager`. Pass `event_bus=None` — `resolve_review` handles that branch. (The plugin-side EventBus is reachable from the API; a follow-up can unify both. Not blocking MTRNIX-314.)

- [ ] **Step 3: Run tests + lint.**
- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/mcp/tools/_memory_deps.py
  git commit -m "feat(MTRNIX-314): wire FreshnessStore + pg_store into MemoryService factory"
  ```

**Acceptance:** `build_memory_service_for_workspace` constructs a service with `freshness_store` set.

---

### Task 9: MCP utility — `parse_status_filter`

**Files:** `src/metatron/mcp/tools/_memory_utils.py`

- [ ] **Step 1: Add helper.**
  ```python
  from metatron.core.models import LifecycleStatus

  def parse_status_filter(
      status: list[str] | None,
  ) -> list[LifecycleStatus] | None:
      if status is None:
          # default = ACTIVE only
          return [LifecycleStatus.ACTIVE]
      if len(status) == 1 and status[0] == "all":
          return None
      out: list[LifecycleStatus] = []
      for s in status:
          try:
              out.append(LifecycleStatus(s))
          except ValueError as exc:
              valid = [v.value for v in LifecycleStatus] + ["all"]
              raise ValueError(
                  f"invalid status '{s}'; valid values: {valid}"
              ) from exc
      return out
  ```

- [ ] **Step 2: Unit test.** In `tests/unit/mcp/test_memory_utils.py` (extend or create): four cases (None, ["all"], ["active","candidate"], ["bogus"]).

- [ ] **Step 3: Run tests + lint.**
- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/mcp/tools/_memory_utils.py tests/unit/mcp/test_memory_utils.py
  git commit -m "feat(MTRNIX-314): parse_status_filter helper"
  ```

**Acceptance:** Helper returns correct shapes; errors carry hint with valid values.

---

### Task 10: Pydantic response models

**Files:** `src/metatron/mcp/tools/models.py`

- [ ] **Step 1: Add `status` field to `MemoryRecordDTO`.**
  ```python
  status: str = "active"  # lowercase LifecycleStatus value; default keeps legacy fixtures green
  ```

- [ ] **Step 2: Add new models.**
  ```python
  class ReviewEntryDTO(BaseModel):
      id: str
      workspace_id: str
      target_id: str
      target_kind: str = "memory_record"
      reason: str
      related_record_id: str | None = None
      content: str = ""
      confidence: float = 0.0
      created_at: datetime | None = None

  class MemoryReviewListResponse(BaseModel):
      entries: list[ReviewEntryDTO]
      count: int
      total: int
      limit: int
      offset: int

  class MemoryReviewResolveResponse(BaseModel):
      success: bool = True
      review_id: str
      target_id: str
      action: str
      old_status: str
      new_status: str
      superseded_by: str | None = None
      machine_event_id: str
  ```

- [ ] **Step 3: Run tests + lint.**
- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/mcp/tools/models.py
  git commit -m "feat(MTRNIX-314): add ReviewEntryDTO + review response models; status on MemoryRecordDTO"
  ```

**Acceptance:** Models import cleanly; existing response tests still green.

---

### Task 11: Modify `metatron_memory_search`

**Files:**
- Modify: `src/metatron/mcp/tools/memory_search.py`
- Create: `tests/unit/mcp/tools/test_memory_search_status_filter.py`

- [ ] **Step 1: Write tests first** (using the FastMCP tool as a plain async function, mocking `build_memory_service_for_workspace` → service with mocked `search`).
  - Default (no `status`) → service.search called with `status_filter=[LifecycleStatus.ACTIVE]`.
  - `status=["all"]` → `status_filter=None`.
  - `status=["active","candidate"]` → service.search called with matching list.
  - `status=["bogus"]` → `INVALID_PARAMS` error response with hint.

- [ ] **Step 2: Edit the tool.**
  Add `status: list[str] | None = None` parameter.
  After `scope_enum` parsing:
  ```python
  try:
      status_filter = parse_status_filter(status)
  except ValueError as exc:
      return {"error": MCPError(
          code=ErrorCode.INVALID_PARAMS,
          message=f"metatron_memory_search: {exc}",
      ).to_dict()}
  ```
  Pass `status_filter=status_filter` through to `service.search(...)`. Populate `record.status.value` into the `MemoryRecordDTO(status=...)` field.

- [ ] **Step 3: Extend the tool description** with the `status` param doc.

- [ ] **Step 4: Run tests + lint + typecheck.**
- [ ] **Step 5: Commit.**
  ```
  git add src/metatron/mcp/tools/memory_search.py tests/unit/mcp/tools/test_memory_search_status_filter.py
  git commit -m "feat(MTRNIX-314): metatron_memory_search accepts status filter"
  ```

**Acceptance:** 4 new tests green.

---

### Task 12: Modify `metatron_memory_list`

**Files:**
- Modify: `src/metatron/mcp/tools/memory_list.py`
- Create: `tests/unit/mcp/tools/test_memory_list_status_filter.py`

- [ ] **Step 1: Write tests first.**
  - Default (no `status`) → `list_records` called with `status=[LifecycleStatus.ACTIVE]`.
  - `status=["all"]` → `list_records(status=None)`.
  - `status=["active","candidate"]` → pass-through.
  - `status=["bogus"]` → `INVALID_PARAMS`.
  - `total` reflects `count_records(status=...)`.

- [ ] **Step 2: Edit the tool.**
  Add `status: list[str] | None = None` param. Parse via `parse_status_filter`. Pass to `pg_store.list_records(status=status_filter)` and `pg_store.count_records(status=status_filter)`.

- [ ] **Step 3: Add `status` field** to each `MemoryRecordDTO` in the response.

- [ ] **Step 4: Run tests + lint + typecheck.**
- [ ] **Step 5: Commit.**
  ```
  git add src/metatron/mcp/tools/memory_list.py tests/unit/mcp/tools/test_memory_list_status_filter.py
  git commit -m "feat(MTRNIX-314): metatron_memory_list accepts status filter"
  ```

**Acceptance:** 5 new tests green.

---

### Task 13: New tool — `metatron_memory_review_list`

**Files:**
- Create: `src/metatron/mcp/tools/memory_review_list.py`
- Modify: `src/metatron/mcp/tools/__init__.py`
- Create: `tests/unit/mcp/tools/test_memory_review_list.py`

- [ ] **Step 1: Write tests first.**
  - Happy path: paginated response, `total` correct.
  - `reason="possible_duplicate"` filter.
  - `record_id="mem_abc"` filter.
  - Missing `workspace_id` → uses `"default"`.
  - Service raises → wrapped `INTERNAL_ERROR`.

- [ ] **Step 2: Create the tool.**
  Mirror `memory_list.py` structure. Description:
  ```
  List pending memory review-queue entries.

  **Parameters:**
  - workspace_id: Target workspace (optional, uses default)
  - reason: Filter: possible_duplicate | possible_contradiction | low_confidence_decision (optional)
  - record_id: Filter to a specific memory record id (optional)
  - limit: Page size, 1..100 (default 20)
  - offset: Pagination offset (default 0)

  **Returns:** Paginated list of ReviewEntry rows for target_kind=memory_record.
  ```
  Body:
  ```python
  async def metatron_memory_review_list(
      workspace_id: str | None = None,
      reason: str | None = None,
      record_id: str | None = None,
      limit: int = 20,
      offset: int = 0,
  ) -> dict[str, Any]:
      try:
          ws_id = workspace_id or "default"
          limit = min(max(1, int(limit)), 100)
          offset = max(0, int(offset))
          service = await _memory_deps.build_memory_service_for_workspace(ws_id)
          entries, total = await service.list_review_entries(
              ws_id, reason=reason, record_id=record_id,
              limit=limit, offset=offset,
          )
          dtos = [
              ReviewEntryDTO(
                  id=e.id, workspace_id=e.workspace_id,
                  target_id=e.target_id, target_kind=e.target_kind,
                  reason=e.reason, related_record_id=e.related_record_id,
                  content=e.content, confidence=e.confidence,
                  created_at=e.created_at,
              )
              for e in entries
          ]
          return MemoryReviewListResponse(
              entries=dtos, count=len(dtos), total=total,
              limit=limit, offset=offset,
          ).model_dump()
      except Exception as exc:
          error = handle_tool_error("metatron_memory_review_list", exc)
          return {"error": error.to_dict()}
  ```

- [ ] **Step 3: Side-effect import** — add `from metatron.mcp.tools import memory_review_list  # noqa: F401` to `__init__.py` (match existing pattern).

- [ ] **Step 4: Run tests + lint + typecheck.**
- [ ] **Step 5: Commit.**
  ```
  git add src/metatron/mcp/tools/memory_review_list.py src/metatron/mcp/tools/__init__.py tests/unit/mcp/tools/test_memory_review_list.py
  git commit -m "feat(MTRNIX-314): metatron_memory_review_list MCP tool"
  ```

**Acceptance:** 5 new tests green. Tool registers with FastMCP on import.

---

### Task 14: New tool — `metatron_memory_review_resolve`

**Files:**
- Create: `src/metatron/mcp/tools/memory_review_resolve.py`
- Modify: `src/metatron/mcp/tools/__init__.py`
- Create: `tests/unit/mcp/tools/test_memory_review_resolve.py`

- [ ] **Step 1: Write tests first.**
  - `keep` → service.resolve_review called with action="keep"; response reflects new_status=active.
  - `archive` → new_status=archived.
  - `merge_into:mem_xyz` → service called; response reflects superseded + superseded_by.
  - `merge_into:` (empty target) → `INVALID_PARAMS`.
  - `merge_into:mem_nonexistent` → `INVALID_PARAMS` (service raises ValueError → wrapped).
  - `discard` → new_status=archived.
  - Unknown action → `INVALID_PARAMS`.
  - Review not found → `DOCUMENT_NOT_FOUND` (service raises `MemoryNotFoundError` → mapped via `handle_tool_error`).
  - `notes` longer than 1024 chars → truncated at service layer (verified).

- [ ] **Step 2: Create the tool.**
  Description:
  ```
  Apply a resolution to a memory review-queue entry.

  **Parameters:**
  - review_id: Review entry id (required)
  - workspace_id: Target workspace (optional, uses default)
  - action: keep | archive | merge_into:<record_id> | discard (required)
  - notes: Free-form audit note, capped at 1024 chars (optional)

  **Returns:** review_id, target_id, action, old_status, new_status,
               superseded_by?, machine_event_id.

  **Semantics:**
  - keep: memory record status → ACTIVE; review entry deleted.
  - archive: status → ARCHIVED.
  - merge_into:<id>: current record status → SUPERSEDED with superseded_by=<id>.
                     Content/tag merge is not performed (future work).
  - discard: status → ARCHIVED (soft delete; no hard DELETE at MCP layer).

  Emits a MachineEvent (event_type=freshness_review_resolved) and publishes
  the FRESHNESS_REVIEW_RESOLVED EventBus event when available.
  ```
  Body calls `service.resolve_review(...)`, maps result to `MemoryReviewResolveResponse`, catches `ValueError` → `INVALID_PARAMS`, lets everything else go through `handle_tool_error`.

- [ ] **Step 3: Side-effect import** in `__init__.py`.

- [ ] **Step 4: Run tests + lint + typecheck.**
- [ ] **Step 5: Commit.**
  ```
  git add src/metatron/mcp/tools/memory_review_resolve.py src/metatron/mcp/tools/__init__.py tests/unit/mcp/tools/test_memory_review_resolve.py
  git commit -m "feat(MTRNIX-314): metatron_memory_review_resolve MCP tool"
  ```

**Acceptance:** 9 new tests green.

---

### Task 15: Integration tests

**Files:**
- Create: `tests/integration/mcp/test_memory_review_end_to_end.py`
- Create: `tests/integration/mcp/test_memory_search_status_live.py`

- [ ] **Step 1: `test_memory_review_end_to_end.py`:**
  Seeds a workspace + memory record, seeds a ReviewEntry directly via `FreshnessStore`, calls `memory_review_list` (expect 1), calls `memory_review_resolve(action="keep")`, then verifies:
  - `memory_records.status` = `active` via PG.
  - `review_entries` has no row for that review_id.
  - `machine_events` has one row with `event_type=freshness_review_resolved`, `actor=mcp_caller`.

- [ ] **Step 2: `test_memory_search_status_live.py`:**
  Seed two records (one ACTIVE, one flipped to ARCHIVED via `update_lifecycle`), index to Qdrant, call `memory_search(top_k=10)` — expect only ACTIVE. Call with `status=["all"]` — expect both. Call with `status=["archived"]` — expect only ARCHIVED.

- [ ] **Step 3: Run `make test-all`.**
- [ ] **Step 4: Commit.**
  ```
  git add tests/integration/mcp/test_memory_review_end_to_end.py tests/integration/mcp/test_memory_search_status_live.py
  git commit -m "test(MTRNIX-314): integration tests for status filter + review tools"
  ```

**Acceptance:** Both integration tests pass against live PG+Qdrant+Redis.

---

### Task 16: `docs/MCP_API.md` update

**Files:** `docs/MCP_API.md`

- [ ] **Step 1: Update `memory_search` table** — add the `status` row. Add a callout below the table listing valid LifecycleStatus values plus `"all"`. Note default `["active"]`.

- [ ] **Step 2: Update `memory_list` table** — same addition.

- [ ] **Step 3: Add `memory_review_list` section** — full parameter table, response example, error codes.

- [ ] **Step 4: Add `memory_review_resolve` section** — full parameter table (including action semantics table), response example, error codes, and a **"Soft delete only"** callout.

- [ ] **Step 5: Commit.**
  ```
  git add docs/MCP_API.md
  git commit -m "docs(MTRNIX-314): MCP_API entries for status filter + review tools"
  ```

**Acceptance:** All 4 tools documented. Links to `HERMES_INTEGRATION.md` intact.

---

### Task 17: Module-level `.claude.md` updates

**Files:**
- Modify: `src/metatron/mcp/.claude/claude.md`
- Modify: `src/metatron/memory/.claude/CLAUDE.md`
- Modify: `src/metatron/storage/.claude/claude.md`

- [ ] **Step 1: MCP docs** — add two bullets under "tools/":
  ```
  ### `tools/memory_review_list.py`
  `memory_review_list(workspace_id, reason?, record_id?, limit, offset)` — paginated list of pending ReviewEntry rows for `target_kind=memory_record`. Delegates to `MemoryService.list_review_entries()`.

  ### `tools/memory_review_resolve.py`
  `memory_review_resolve(review_id, workspace_id, action, notes?)` — apply `keep | archive | merge_into:<id> | discard` to a review entry. Soft-transitions only (no hard DELETE). Emits a MachineEvent and fires the `FRESHNESS_REVIEW_RESOLVED` EventBus event.
  ```
  Also extend the entries for `memory_search` / `memory_list` with the `status` parameter.

- [ ] **Step 2: Memory docs** — extend `service.py` bullet list with `list_review_entries` + `resolve_review`. Add a note on the new constructor kwargs.

- [ ] **Step 3: Storage docs** — extend `memory_postgres.py` bullet list with `list_records(status=)` + `count_records(status=)` + `get_many_statuses`. Extend `memory_qdrant.py` with `status` payload + `search(status_exclude=)`. Extend `freshness_pg.py` with `count_review_entries` + `delete_review_entry`.

- [ ] **Step 4: Commit.**
  ```
  git add src/metatron/mcp/.claude/claude.md src/metatron/memory/.claude/CLAUDE.md src/metatron/storage/.claude/claude.md
  git commit -m "docs(MTRNIX-314): module CLAUDE.md updates for status filter + review tools"
  ```

**Acceptance:** Every touched module's `.claude.md` references the new surface.

---

### Task 18: CHANGELOG

**Files:** `CHANGELOG.md`

- [ ] **Step 1: Add entry** under the current unreleased section:
  ```
  - **MCP:** `memory_search` and `memory_list` now accept a lifecycle `status`
    filter (default: `["active"]`, pass `status=["all"]` to disable).
    Added `memory_review_list` and `memory_review_resolve` MCP tools for the
    freshness pipeline's review queue (MTRNIX-314).
  ```

- [ ] **Step 2: Commit.**
  ```
  git add CHANGELOG.md
  git commit -m "docs(MTRNIX-314): CHANGELOG entry"
  ```

---

### Task 19: Final verification + PR

- [ ] **Step 1: Run full test matrix.**
  `make lint` / `make typecheck` / `make test` — separately.
  `make test-all` — integration suite.
- [ ] **Step 2: Grep guardrails.**
  - `grep -rn "workspace_id" src/metatron/mcp/tools/memory_review_*.py` — hits every public entry point.
  - `grep -rn "import metatron.agent\|import metatron.channels\|api.routes.chat\|api.routes.finops" src/metatron/mcp/tools/memory_review_*.py src/metatron/memory/resolution.py` — empty.
  - `grep -rn "freshness_pg" src/metatron/mcp/tools/memory_review_*.py` — empty (tools go through service, not storage).
- [ ] **Step 3: Open PR.**
  Title: `feat(MTRNIX-314): memory MCP lifecycle-status filter + review queue tools`
  Body summarises: 2 modified tools, 2 new tools, 1 new event constant, no migration. Flag for enterprise: new `FRESHNESS_REVIEW_RESOLVED` event is additive. No Co-Authored-By, no Claude Code badge.

**Acceptance:** Green CI. All 9 open questions from the spec closed in-code.

---

## Risks watchlist

- **Qdrant payload drift** — test-all + a manual post-merge spot check that recently-written records show `status` in payload. Backfill script at hand.
- **Graph-only hit filtering correctness** — integration test covers the path; unit test asserts batched lookup.
- **Event wiring** — MCP path currently has no EventBus handle; `FRESHNESS_REVIEW_RESOLVED` will only propagate once API-side callers land. Acceptable; MachineEvent row covers the durable audit.
- **`merge_into` surprise** — content not merged. Documented in MCP_API.md; future work.

---

## Coordination points

- **`core/interfaces.py`** unchanged.
- **`core/events.py`** gains one constant (additive).
- **`review_entries` schema** unchanged (migration 018 already in develop).
- **Enterprise plugin heads-up (PR body):**
  - New event `FRESHNESS_REVIEW_RESOLVED` (`event_type="freshness_review_resolved"`) will be emitted by `MemoryService.resolve_review` when an EventBus is wired.
  - `MemoryRecordDTO` gains a `status` field — downstream DTOs that re-serialize should accommodate.
  - No DB schema change. No API shape change on existing tools (the `status` param is optional with a default).
````

