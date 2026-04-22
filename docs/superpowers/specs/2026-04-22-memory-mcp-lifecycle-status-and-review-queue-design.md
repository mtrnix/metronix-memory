# Memory MCP: lifecycle-status filter + review queue tools — Design

**Date:** 2026-04-22
**Jira:** MTRNIX-314 — Memory MCP: lifecycle-status filter + review queue tools.
**Depends on:** MTRNIX-304 (Phase A memory freshness — merged, PR #83), MTRNIX-313 (Phase B KB freshness + shared `FreshnessStore` — merged, PR #85).
**Parent epic:** MTRNIX-227 (Agent Memory System, WS1).
**Author:** Architect (agent-team)
**Status:** Draft — ready for implementation plan

## Goal

Expose the freshness artefacts produced by MTRNIX-304 / 313 to external agent runtimes (Hermes, OpenClaw, Cursor, Claude Desktop) over MCP:

1. Add a `status` lifecycle filter to `metatron_memory_search` and `metatron_memory_list`; default to only returning `ACTIVE` records so agents do not see ARCHIVED/SUPERSEDED/CONFLICTED/REVIEW_NEEDED junk.
2. Add two new MCP tools — `metatron_memory_review_list` and `metatron_memory_review_resolve` — that let an agent enumerate and act on the review queue rows that the freshness pipeline's Reconciler (duplicate-detection) and DecisionEngine (low-confidence routing) create.

All changes are additive. Flags are not required — the freshness producer already runs behind `METATRON_FRESHNESS_ENABLED`; the MCP surface just reads whatever the freshness worker has written. When the worker is off, review queue is empty and the filter is a no-op.

## Non-goals

- Control Center / metatronui-cc review queue UI (separate epic, blocked on repo creation).
- KB (raw_documents) review queue tools — out of scope per Jira AC (Control Center scope). This ticket's `target_kind` is hard-coded to `memory_record`.
- Memory-aware `/v1/chat/completions` injection (MTRNIX-275).
- New RBAC roles. The current 3-role model (viewer/editor/admin) and the MCP bearer-token gate stay unchanged. 5-role migration (Agent Admin) is a future ticket; this spec calls out the migration point but does not block on it.
- Hard-delete of memory records via MCP. `discard` in `memory_review_resolve` is soft (status → ARCHIVED); a future `memory_force_delete` admin-only tool is noted but not part of this ticket.
- Content/tag auto-merge on `merge_into:<id>`. The current record is marked SUPERSEDED with `superseded_by=<id>`; content merging is a separate UX problem, deferred.

## Constraints

- **Layer boundaries.** Tool files sit at L3 (`mcp/tools/*`). They MUST go through `MemoryService` / `FreshnessStore` at L1-L3; they MUST NOT call `storage/freshness_pg.py` directly bypassing the service. Service layer gets two new methods: `list_review_entries(...)` and `resolve_review(...)`.
- **Zero-plugin compat.** Core must work with no plugins installed.
- **Workspace isolation.** Every tool takes `workspace_id`; every PG query, Qdrant filter, and `FreshnessStore` call carries it.
- **Async everywhere.**
- **No new imports into** `agent/`, `channels/`, `api/routes/chat.py`, `api/routes/finops.py`.
- **No changes to `core/interfaces.py`.** One additive constant in `core/events.py`.
- **Backwards compatibility:** existing callers that do not pass `status` see the new default behaviour (only ACTIVE). This is a behaviour change relative to "return whatever is in the table" — but the table has no non-ACTIVE rows until the freshness worker is enabled, so for deployments that have not turned on `METATRON_FRESHNESS_ENABLED` the behaviour is unchanged in practice.

## Current state summary

From PR #83 (MTRNIX-304) + PR #85 (MTRNIX-313):

| Artefact | Location | Role for MTRNIX-314 |
|---|---|---|
| `LifecycleStatus` enum | `core/models.py` | Used in filter params, in `update_lifecycle` calls, in `MachineEvent` payload. `MemoryStatus = LifecycleStatus` alias stays. |
| `MemoryRecord.status` field (with DB default `ACTIVE`) | `core/models.py` + `storage/memory_postgres.py` | Filter target. Must become Qdrant payload too (currently not in payload). |
| `ReviewEntry` dataclass (`target_id`, `target_kind`, `record_id` alias) | `core/models.py` | Returned by new `memory_review_list`. |
| `review_entries` table with `target_kind` discriminator | migration 017 + 018 | `memory_review_list` filters on `target_kind='memory_record'`. |
| `FreshnessStore.list_review_entries(workspace_id, *, target_kind, record_id / target_id, limit)` | `storage/freshness_pg.py` | Directly usable. We add `offset` + `reason` filter + `count`. |
| `FreshnessStore.save_review_entry` / `find_review_entry` | same | Used by Reconciler / apply_decision. Unchanged here. |
| `FreshnessStore.save_machine_event` | same | Used to append `FRESHNESS_REVIEW_RESOLVED` event. |
| `MemoryPostgresStore.update_lifecycle(workspace_id, record_id, *, status=, superseded_by=, ...)` | `storage/memory_postgres.py` | Used by `resolve_review`. |
| `MemoryPostgresStore.list_records(...)` — no status filter | `storage/memory_postgres.py` | Extended with `status: list[LifecycleStatus] | None`. |
| `MemoryQdrantStore.upsert` — payload has no `status` field | `storage/memory_qdrant.py` | **Must be extended** to write `status` so search-time payload filter works. Plus `update_payload` already exists for lazy sync. |
| Event constants `FRESHNESS_JOB_ENQUEUED / JOB_PROCESSED / DECISION_APPLIED / REVIEW_CREATED` | `core/events.py` | **Add one new:** `FRESHNESS_REVIEW_RESOLVED`. |
| Reconciler comment `event_bus wiring deferred to MTRNIX-314 (review queue MCP surface)` | `freshness/stages/reconciler.py` line 191 | This ticket closes that loop via integration test coverage; event constants already exist. |
| MCP bearer-token auth middleware | `mcp/server.py` + `mcp/auth.py` | Unchanged. Same gate applies to new tools. |

## Tool contracts

### Modified: `metatron_memory_search`

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | — | Natural-language query |
| `agent_id` | string | yes | — | Agent identity |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `scope` | string | no | null | `global \| per_agent \| session` |
| `tags` | list[string] | no | null | Intersection filter |
| `session_id` | string | no | null | Enables session-boost leg |
| `top_k` | int | no | 5 | 1..50 |
| **`status`** | **list[string]** | **no** | **`["active"]`** | **Lifecycle statuses to include. Strings from `LifecycleStatus` enum (lowercase). Special value `"all"` disables filtering.** |

- Invalid enum value in `status` → `INVALID_PARAMS` with a hint listing valid values.
- `status=["all"]` short-circuits the filter on every leg — pass `None` down to `MemorySearchService.hybrid_search`.
- Response shape: **unchanged** (`MemorySearchToolResponse`). Each `MemoryRecordDTO` gains a `status` field (additive; defaults to `"active"` for records without explicit status).

### Modified: `metatron_memory_list`

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `agent_id` | string | yes | — | Agent identity |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `scope` | string | no | null | Scope filter |
| `tags` | list[string] | no | null | Tags post-filter |
| `limit` | int | no | 20 | 1..100 |
| `offset` | int | no | 0 | Pagination offset |
| **`status`** | **list[string]** | **no** | **`["active"]`** | **Same semantics as `memory_search`.** |

- `status` is pushed down into the PG WHERE clause (single IN clause over lowercase enum values). `status=["all"]` omits the WHERE.
- `total` counts only rows matching the status filter (so UI pagination stays honest).
- `MemoryRecordDTO` gains `status` field.

### New: `metatron_memory_review_list`

Paginated enumeration of review entries for `target_kind="memory_record"`.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `workspace_id` | string | no | `"default"` | Target workspace |
| `agent_id` | string | no | null | Reserved. Current `ReviewEntry` has no `agent_id` column — filter is via the target record's agent_id, not the review row. If passed, a PG JOIN to `memory_records` filters by `memory_records.agent_id`. |
| `reason` | string | no | null | Filter: `possible_duplicate \| possible_contradiction \| low_confidence_decision` (free-form string, validated against known set; unknown passes through as a free-form filter — forward-compatible). |
| `record_id` | string | no | null | Filter to review entries for a specific record. |
| `limit` | int | no | 20 | 1..100 |
| `offset` | int | no | 0 | Pagination offset |

Response shape (Pydantic `MemoryReviewListResponse`):

```jsonc
{
  "entries": [
    {
      "id": "review_abc...",
      "workspace_id": "MTRNIX",
      "target_id": "mem_def...",         // the memory_record being reviewed
      "target_kind": "memory_record",    // always; hard-wired
      "reason": "possible_duplicate",
      "related_record_id": "mem_ghi...", // null for low_confidence_decision
      "content": "User prefers dark mode",
      "confidence": 0.87,
      "created_at": "2026-04-22T10:15:00+00:00"
    }
  ],
  "count": 1,
  "total": 3,
  "limit": 20,
  "offset": 0
}
```

Errors: `WORKSPACE_NOT_FOUND`, `INVALID_PARAMS`, `INTERNAL_ERROR`.

### New: `metatron_memory_review_resolve`

Apply a resolution to a single review entry. Idempotent on repeated calls with the same action (second call is a no-op if the review entry is gone). Emits a `MachineEvent` (audit) and publishes `FRESHNESS_REVIEW_RESOLVED` on the plugin EventBus.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `review_id` | string | yes | — | Review entry id |
| `workspace_id` | string | no | `"default"` | Target workspace |
| `action` | string | yes | — | `keep \| archive \| merge_into:<record_id> \| discard` |
| `notes` | string | no | null | Free-form audit note. Stored in MachineEvent payload. |

Action semantics:

| Action | `memory_records.status` | Other PG side-effects | Soft/Hard |
|---|---|---|---|
| `keep` | → `active` | `verification_state="keep_resolved"` | Soft |
| `archive` | → `archived` | `verification_state="archived_via_review"` | Soft |
| `merge_into:<id>` | → `superseded` | `superseded_by=<id>`, `verification_state="merged_via_review"` | Soft. Content/tag auto-merge is deferred. |
| `discard` | → `archived` | `verification_state="discarded_via_review"` | **Soft**. Hard delete NOT provided here. |

Side-effects per action:
1. Validate `action` string; parse `merge_into:<id>` into `(action_kind="merge_into", target_id=<id>)`.
2. Load review entry via `FreshnessStore.list_review_entries(workspace_id, target_id=<review_entry.target_id>)` to confirm existence. If missing → `DOCUMENT_NOT_FOUND` ("Review entry not found or already resolved").
3. Load target memory record via `MemoryPostgresStore.get(workspace_id, entry.target_id)`. If missing → `DOCUMENT_NOT_FOUND`.
4. Run `MemoryPostgresStore.update_lifecycle` with the transition above. Returns the updated record (old_status captured before update for the event payload).
5. For `merge_into`: additionally validate the target `<id>` exists in the same workspace (otherwise `INVALID_PARAMS`). Emit a best-effort `update_payload` on Qdrant with `status="superseded"` (non-blocking).
6. Delete the review entry via `FreshnessStore.delete_review_entry(workspace_id, review_id)` (new method — small addition).
7. Append `MachineEvent(event_type="freshness_review_resolved", target_kind="memory_record", target_id=..., actor="mcp_caller", payload={...})`.
8. `event_bus.emit(FRESHNESS_REVIEW_RESOLVED, payload)` — only when an `EventBus` is wired into the service (it is, via `MemoryService`).

Response (Pydantic `MemoryReviewResolveResponse`):

```jsonc
{
  "success": true,
  "review_id": "review_abc...",
  "target_id": "mem_def...",
  "action": "keep",
  "old_status": "review_needed",
  "new_status": "active",
  "superseded_by": null,
  "machine_event_id": "evt_xyz..."
}
```

Errors: `DOCUMENT_NOT_FOUND` (review entry or record missing), `INVALID_PARAMS` (malformed action, bad `merge_into:` target), `INTERNAL_ERROR`.

## Data model notes

- **`review_entries` table:** unchanged (already has `target_kind` + `target_id` after migration 018).
- **`memory_records` table:** unchanged. `status`, `superseded_by`, `verification_state` already exist.
- **Qdrant memory collection `mem_agent_memory_{workspace_id}`:** payload gains one field — `status` (keyword). No payload index required for Phase 1 (the filter runs over a small per-workspace set; we can add an index in a follow-up if observed latency justifies). Written on every `upsert`; `update_payload(record_id, {"status": <v>})` on every `update_lifecycle` that changes status. Existing points without `status` are treated as `"active"` for filtering purposes — we use `MatchExcept` on the excluded set rather than `MatchValue` on the included set, so "no status field → included" matches the conservative default (new filter ≡ old behaviour for legacy points).

## Filter placement decision

**Push-down filtering at every layer.** Rationale: post-filter breaks the `top_k` contract if ARCHIVED dominates.

Call-site changes:

1. **`MemoryPostgresStore.list_records(workspace_id, *, agent_id, scope, status, limit, offset)`** — gains `status: list[LifecycleStatus] | None`; WHERE clause adds `AND status = ANY(:status_list)` when not None. `count_records` gets the same argument (so `total` is filter-consistent).
2. **`MemoryQdrantStore.search(...)`** — gains `status_exclude: list[str] | None` kwarg. When set, the Qdrant `Filter.must_not` grows a `FieldCondition(key="status", match=MatchAny(any=status_exclude))`. Filter semantics: "exclude any record whose `status` is in this set." The MCP tool computes the exclude set as `all LifecycleStatus values` minus the requested include set, which means legacy points (no `status` in payload) pass through — correct.
3. **`MemorySearchService.hybrid_search(..., status_filter: list[LifecycleStatus] | None = None)`** — passes the exclude set to Qdrant. For the Neo4j graph leg (no content — `_hydrate_graph_record` uses `session_lookup` for content), the hit is post-filtered via a batched `MemoryPostgresStore.get_many_statuses(workspace_id, record_ids) -> dict[str, LifecycleStatus]` (new tiny helper) after leg fan-in but before the blend. For the Redis session leg: session records are treated as implicitly `ACTIVE` — they have TTL semantics; the freshness pipeline does not touch them. Session hits are never filtered out by status.
4. **MCP tool level** — parses + validates the `status` parameter, converts `"all"` to `None`, and hands the rest down.

The memory Qdrant payload upgrade is a one-time schema-ish change. A backfill script is provided but running it is optional: records stored before this ticket lands have no `status` in Qdrant, which correctly behaves as "ACTIVE" under the exclude-filter semantics.

## MachineEvent + EventBus emission

Every `memory_review_resolve` call writes exactly one `MachineEvent` to `machine_events` and fires exactly one `EventBus` event (`FRESHNESS_REVIEW_RESOLVED`).

- **MachineEvent payload fields:**
  - `event_type`: `"freshness_review_resolved"`
  - `actor`: `"mcp_caller"` (distinguishes from `"freshness_worker"` which is the default on automated rows)
  - `target_kind`: `"memory_record"`
  - `target_id`: the resolved memory record id
  - `payload`:
    ```json
    {
      "review_entry_id": "<review_id>",
      "action": "keep|archive|merge_into|discard",
      "merge_into_target_id": "<id|null>",
      "old_status": "<LifecycleStatus value>",
      "new_status": "<LifecycleStatus value>",
      "superseded_by": "<id|null>",
      "notes": "<free-form string or null>"
    }
    ```
- **EventBus payload** (`FRESHNESS_REVIEW_RESOLVED`):
  ```json
  {
    "workspace_id": "<ws>",
    "target_kind": "memory_record",
    "target_id": "<record_id>",
    "review_entry_id": "<review_id>",
    "action": "keep|archive|merge_into|discard",
    "old_status": "<v>",
    "new_status": "<v>"
  }
  ```

This mirrors the Phase A payload convention documented at `core/events.py` lines 52-58. Enterprise subscribers can filter on `action` or `target_kind`.

## Service layer additions

Two new methods on `MemoryService`:

```python
async def list_review_entries(
    self,
    workspace_id: str,
    *,
    agent_id: str | None = None,
    reason: str | None = None,
    record_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[ReviewEntry], int]:  # (page, total)
    ...

async def resolve_review(
    self,
    workspace_id: str,
    *,
    review_id: str,
    action: str,
    notes: str | None = None,
    actor: str = "mcp_caller",
) -> ReviewResolution:  # small dataclass: review_id, target_id, action, old_status, new_status, superseded_by, machine_event_id
    ...
```

- Both methods wire the `FreshnessStore` dependency. `MemoryService.__init__` grows an optional `freshness_store: FreshnessStore | None = None` kwarg (default `None` keeps legacy tests green — methods raise `RuntimeError` when called without wiring).
- `_memory_deps.build_memory_service_for_workspace` constructs a `FreshnessStore` from the same `AsyncEngine` and passes it in.
- `list_review_entries` calls `FreshnessStore.list_review_entries(workspace_id, target_kind="memory_record", record_id=record_id, limit, offset, reason=reason)` — `FreshnessStore.list_review_entries` is extended with `offset`, `reason`, and a companion `count_review_entries(workspace_id, *, target_kind, record_id, reason) -> int`.
- `resolve_review` orchestrates steps 1-8 under "action semantics" above. All PG writes run in one `async with engine.begin()` where possible — lifecycle-update + delete-review + machine-event-insert go in a single transaction for atomicity. The Qdrant payload update and EventBus emit are outside the transaction (best-effort).

A tiny new `FreshnessStore.delete_review_entry(workspace_id, review_id)` method is needed (symmetric with `save_review_entry`). One-line SQL.

## Qdrant payload update for status

In `MemoryQdrantStore.upsert`, add `"status": record.status.value` to the `payload` dict.

Add a new method `MemoryQdrantStore.update_status_payload(record_id, status)` — or just reuse existing `update_payload(record_id, {"status": status.value})`. Called from `MemoryPostgresStore.update_lifecycle` via `MemoryService.resolve_review` only — we do NOT wire it into the freshness-worker `update_lifecycle` path in this ticket (that is Phase A's concern; a follow-up can lift it). For MTRNIX-314, the guarantee is: **whenever MCP tools change status, Qdrant payload is synced within the tool call** (best-effort). Worker-driven status changes land in Qdrant lazily (next `upsert`) — acceptable because the default filter excludes ARCHIVED/SUPERSEDED, and the worker only writes those on records that are then rare in hot-path search. A low-priority follow-up ticket can close that gap.

## RBAC

No new RBAC checks at the MCP layer. The `METATRON_MCP_API_KEY` bearer-token gate covers all 4 tools. The spec calls out that after the 5-role RBAC migration (future ticket), `memory_review_resolve` should be gated to Agent Admin role.

## Backward compatibility

- `memory_search` / `memory_list` callers that do not pass `status`: see only `ACTIVE` records. For deployments with `METATRON_FRESHNESS_ENABLED=false` (the default), all memory records are implicitly ACTIVE (either explicit ACTIVE or legacy pre-migration rows that default to `active`). Behaviour unchanged in practice. For deployments that have turned on the worker, non-ACTIVE rows are now correctly hidden (the whole point of the ticket).
- `MemoryRecordDTO` gains a `status` field. Clients using Pydantic-generated schemas see an additional optional field; JSON consumers ignore new keys. Not a breaking change.
- `MemoryService` constructor gains an optional `freshness_store` kwarg (default `None`). Old construction paths still work; the new review methods raise `RuntimeError("freshness_store not configured")` when called without wiring. Test fixtures that don't wire it keep passing.
- No schema migration. No Alembic migration 019.
- `FreshnessStore.list_review_entries` signature gains `offset=`, `reason=` keyword-only args with defaults — non-breaking.

## Test plan

### Unit tests

1. `tests/unit/mcp/tools/test_memory_search_status_filter.py`
   - Default: only `ACTIVE` records returned.
   - `status=["all"]`: no filter applied (pass-through mock checks exclude_set is `None`).
   - `status=["active","candidate"]`: exclude set = all enum values minus {active, candidate}.
   - Invalid value → `INVALID_PARAMS` with hint listing valid enum values.
2. `tests/unit/mcp/tools/test_memory_list_status_filter.py`
   - Same cases, PG push-down via mocked `list_records(status=[...])`.
   - `total` reflects filtered count.
3. `tests/unit/mcp/tools/test_memory_review_list.py`
   - Happy path: paginated response, `total` correct.
   - `reason` filter.
   - `record_id` filter.
   - Invalid workspace_id → error.
4. `tests/unit/mcp/tools/test_memory_review_resolve.py`
   - `keep` → status → ACTIVE, review deleted, MachineEvent written, EventBus fired.
   - `archive` → status → ARCHIVED.
   - `merge_into:<id>` with existing target → status → SUPERSEDED, `superseded_by=<id>`.
   - `merge_into:<id>` with non-existent target → `INVALID_PARAMS`.
   - `discard` → status → ARCHIVED, `verification_state="discarded_via_review"`.
   - Non-existent review → `DOCUMENT_NOT_FOUND`.
   - Non-existent memory record → `DOCUMENT_NOT_FOUND`.
   - Malformed `action` → `INVALID_PARAMS`.
   - Idempotency: re-running same resolve after first succeeds → `DOCUMENT_NOT_FOUND`.
5. `tests/unit/memory/test_service_review.py`
   - `MemoryService.list_review_entries` delegates correctly.
   - `MemoryService.resolve_review` orchestrates PG + review delete + MachineEvent + EventBus in right order.
   - `MemoryService.resolve_review` without `freshness_store` wired → `RuntimeError`.
6. `tests/unit/memory/test_search_status_pushdown.py`
   - `MemorySearchService.hybrid_search(status_filter=...)` passes correct exclude set to `qdrant.search(status_exclude=...)`.
   - Graph-only hit with excluded status is dropped via PG batch lookup.
   - Session hits are never filtered.
7. `tests/unit/storage/test_memory_postgres_list_status.py`
   - `list_records(status=[ACTIVE])` WHERE clause.
   - `count_records(status=[ACTIVE])`.
8. `tests/unit/storage/test_memory_qdrant_status_payload.py`
   - `upsert` writes `status` payload.
   - `search(status_exclude=...)` builds correct Qdrant `Filter.must_not`.
9. `tests/unit/storage/test_freshness_pg_review_extensions.py`
   - `list_review_entries(offset=, reason=)`.
   - `count_review_entries(...)`.
   - `delete_review_entry(workspace_id, id)`.

### Integration tests

10. `tests/integration/mcp/test_memory_review_end_to_end.py`
    - Seed a memory record, run freshness worker's Reconciler to create a review entry, call `memory_review_list` (see 1 entry), call `memory_review_resolve(action="keep")`, verify status → ACTIVE, review entry gone, MachineEvent exists. Requires live PG + Redis + Qdrant.
11. `tests/integration/mcp/test_memory_search_status_live.py`
    - Seed an ACTIVE + an ARCHIVED record, search → only ACTIVE returned. Search with `status=["all"]` → both.

## Rollout

No flag. No migration. Behaviour is opt-in to the degree that `status=["all"]` is available as escape hatch.

**Order of merge:**
1. Data layer (PG `list_records(status=)`, Qdrant `upsert` adds status, Qdrant `search(status_exclude=)`, `FreshnessStore` additions).
2. Service layer (`MemorySearchService` status push-down, `MemoryService.list_review_entries` + `resolve_review`).
3. MCP layer (modified `memory_search` / `memory_list`, new `memory_review_list` / `memory_review_resolve`).
4. Docs (`MCP_API.md` + `src/metatron/mcp/.claude/claude.md`).

One PR. Under 20 files. No compose changes, no deployment work.

## Security considerations

- `discard` is soft — no hard DELETE. This keeps the blast radius bounded even when an MCP caller is compromised.
- `notes` field is stored verbatim in `machine_events.payload` (JSONB). Length cap at 1 KB enforced at MCP layer to prevent log-stuffing.
- `merge_into:<id>` validates target exists in same workspace — prevents cross-workspace merges.
- No PII in new event payloads. `payload` carries ids and status enums only; content is not logged.

## Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Qdrant payload drift — `status` out of sync with PG | LOW-MEDIUM | Best-effort write on `upsert` + `resolve_review`. MCP exclude-filter semantics treat missing `status` as `ACTIVE` → drift causes briefly-included ARCHIVED rows, never excluded ACTIVE rows. Backfill script ships; running it is optional. Worker-side lazy sync covered by follow-up. |
| Default filter breaks existing callers | LOW | Only changes behaviour for deployments running the freshness worker. For dev defaults (worker off), table has no non-ACTIVE rows. `status=["all"]` escape hatch covers debugging. |
| `memory_review_resolve(discard)` misunderstood as hard delete | LOW | Response payload always includes `new_status="archived"`. Docs call this out. `notes` stored. |
| Concurrent resolves on the same review entry | LOW | Service-layer transaction around lifecycle-update + review-delete + machine-event. Second resolver sees review entry missing → `DOCUMENT_NOT_FOUND`, consistent idempotency. |
| Graph-only hits (no Qdrant peer) leak non-ACTIVE status | LOW | Batched PG `get_many_statuses` lookup post-hoc in `MemorySearchService`. |
| Session cache hits with stale status | LOW | Session-cache records are always `ACTIVE` by construction (TTL semantics; worker does not touch them). Documented. |
| Enterprise plugin doesn't know about new event | LOW | `FRESHNESS_REVIEW_RESOLVED` constant is additive. Plugins that don't subscribe don't see it. PR description flags the addition. |

## Open questions — closed

1. **Default status set.** `{ACTIVE}`. Jira AC said ACTIVE+CANDIDATE but Curator-promotion semantics in Phase A make CANDIDATE mean "unvetted in-flight" — not appropriate for default recall. CONFLICTED / REVIEW_NEEDED are never in default.
2. **`status=["all"]` escape hatch.** Same gate as other MCP tools (bearer token). No per-role split in MCP today.
3. **Filter location.** Push-down at Qdrant payload + PG WHERE + graph-leg batched PG lookup. Session leg implicit-ACTIVE. `top_k` contract preserved.
4. **Resolve action semantics.** See "Tool contracts". Content/tag merge deferred. `discard` is soft (status=ARCHIVED), not hard DELETE.
5. **`target_kind` in review tools.** Hard-wired `memory_record`. KB scope is Control Center.
6. **RBAC.** Current bearer-token only. Future 5-role model gates `resolve` to Agent Admin; noted.
7. **MachineEvent payload.** Fields listed above; mirrors `FRESHNESS_DECISION_APPLIED` shape.
8. **Pagination.** Offset-based, limit cap 100.
9. **Enterprise coordination.** Additive only: new constant `FRESHNESS_REVIEW_RESOLVED`, new `status` field on `MemoryRecordDTO`. Courtesy note in PR body.

## Acceptance criteria (reviewer checklist)

1. `make lint` / `make typecheck` / `make test` green.
2. `memory_search` / `memory_list` accept `status` param; default `["active"]`; `"all"` disables.
3. Qdrant `mem_agent_memory_{ws}` collection: new points carry `status` payload.
4. `memory_review_list` paginates review entries for `target_kind="memory_record"`.
5. `memory_review_resolve` applies all four actions; emits MachineEvent + EventBus event.
6. `docs/MCP_API.md` documents the 4 tools fully.
7. `src/metatron/mcp/.claude/claude.md` lists the new tools.
8. Grep: `grep -rn workspace_id src/metatron/mcp/tools/memory_review_*.py` hits every public entry point.
9. No imports from `agent/`, `channels/`, `api/routes/chat.py`, `api/routes/finops.py`.
10. `core/interfaces.py` unchanged.
11. Phase A + Phase B tests still green.
````

