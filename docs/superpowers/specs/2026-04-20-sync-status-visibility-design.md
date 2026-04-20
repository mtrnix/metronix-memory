# MTRNIX-309 — Connector Sync Status Visibility & Recovery

**Date:** 2026-04-20
**Author:** Konstantin (with Claude)
**Jira:** [MTRNIX-309](https://mtrnix.atlassian.net/browse/MTRNIX-309) "Bug: When running Jira Sync issues are not synced nor ingested in memory"
**Status:** Draft — awaiting review
**Scope:** metatron-core + metatron-ui (metatronui-kb)

## Problem Statement

The original ticket title suggests Jira sync does not persist issues, but investigation on the live local stack (workspace `MTRNIX`, Jira connection `9e5d3bbae9894808a0d12a8f6f3d796a`) shows sync *does* work end-to-end: 297 `raw_documents`, all `qdrant_synced=true`, 285/297 `graph_synced=true`. `JiraConnector.fetch()` invoked standalone returns 297 docs in 6.7 seconds with no errors. A manually-triggered sync during investigation completed successfully in ~13 minutes (dominated by Phase 4 graph extraction) and produced a correct `sync_logs` row.

The real defects are **observability and recovery** — every sync that does not reach its `finally` block leaves no evidence, and there is no path to recover the connection state. The Confluence connection has been `status="syncing"` with no `sync_logs` row since 2026-04-17: a live example.

### Bug A — `connection.status="syncing"` never clears (critical)

`_run_connection_sync` (`src/metatron/api/routes/connections.py`) sets `status="syncing"` at start and relies on the `finally` block to set it to `"active"` or `"error"`. But if the FastAPI `BackgroundTasks` coroutine is destroyed before `finally` runs — API restart, `asyncio.CancelledError`, OS-level kill, Phase-4 LLM hang — the status stays `"syncing"` forever.

Observed: the MTRNIX-Jira connection has been `status="syncing"` since 2026-04-17 despite sync runs completing their data writes on 2026-04-20. The UI button `ConnectionCard.tsx:209` disables the Sync button while `connection.status === 'syncing'` — so the user cannot retry.

### Bug B — `sync_logs` lost on any abnormal termination (critical)

`sync_logs` only receives a row if `_run_connection_sync` reaches its `finally` block. Observation on the local stack: **2 rows across 3 days**, despite at least three sync runs executing (the Confluence connection is still `status="syncing"` since 2026-04-17 with no corresponding log). Any sync that dies before `finally` — API restart mid-run, `asyncio.CancelledError`, Phase-4 LLM hang that outlives the process — leaves no trace.

Side-effect: `GET /api/v1/dashboard/sync/history` under-counts failures. Any UI that tries to show "the last N attempts" sees only the successful minority.

### Bug C — UI gives no result feedback (UX)

`ConnectionCard.handleSync` (`metatronui-kb/src/components/sources/ConnectionCard.tsx`) only shows `toast.success('Sync started')`. Card footer only renders `last_synced_at` ("Synced 3 days ago"). There is no count of documents fetched/new/updated/chunks, no error surface beyond `connection.error_message`, and no per-connection history panel — even though the backend writes richly populated `SyncLogRow` records.

Combined with A+B, the user has no evidence the sync ever ran.

## Non-Goals

- **Phase-4 graph-processing hangs.** LLM-based NER extraction is the likely reason some tasks never reach `finally`. That is a separate defect (candidate for its own ticket) — this design only ensures we surface the failure, not that we eliminate it.
- **Real-time progress indicator during sync.** Nice-to-have for long graph runs, not required to close 309.
- **Push notifications / email on failure.** Out of scope.
- **Fixing stuck connections retroactively via migration.** A manual `UPDATE connections SET status='error' WHERE status='syncing'` is enough for existing rows; recovery logic prevents the recurrence.

## Design

### B first: reliable `sync_logs` writes (blocks A and C)

`_run_connection_sync` is restructured so that an initial `SyncLogRow` is persisted *immediately* — synchronously, before any long-running work — with `status="running"`. Subsequent completion/failure paths UPDATE the existing row by `sync_id`.

```
trigger_sync
  → mark connection status='syncing'
  → INSERT sync_logs (sync_id, status='running', documents_fetched=0, ..., created_at=now)
    ^ synchronous, blocking; must commit before returning 202
  → schedule background _run_connection_sync(sync_id, ...)
  → return 202 { sync_id, connection_id, connector_type }

_run_connection_sync (background)
  try:
    ... phases 1-4 ...
    status = "success" | "partial"
  except:
    status = "failed"
  finally:
    UPDATE sync_logs SET status=final, documents_*=..., qdrant_chunks=..., errors=..., duration_ms=... WHERE id=sync_id
    UPDATE connections SET status='active'|'error', last_synced_at=..., error_message=... WHERE id=connection_id
```

**Guarantee:** even when the coroutine is destroyed before `finally`, the `status='running'` row remains. Recovery (A) can then turn it into `status='failed'` on next startup.

**Schema:** no migration. `SyncLogRow.status` is already `String(32)` and accepts the new literal `"running"`.

### A: startup recovery + watchdog

Two complementary recovery paths.

**Startup recovery (in `api/app.py` lifespan, after migrations, before the app starts serving):**

1. For every `sync_logs` row with `status="running"`:
    - Set `status="failed"`, `errors=["Sync interrupted (API restart)"]`, `duration_ms = now - created_at`.
2. For every `connections` row with `status="syncing"`:
    - Set `status="error"`, `error_message="Sync interrupted (API restart). Please retry."`.

Both operations are idempotent, run in a single transaction each, and log counts via structlog.

**Watchdog (out of scope for MVP, called out for later ticket):** periodically (e.g. every 5 min) reconcile any `sync_logs.status="running"` where `created_at < now - SYNC_STALE_MINUTES` (default 60 min). Only mentioned so reviewers know the design leaves room for it — not implemented in this PR.

### C: UI visibility in `metatronui-kb`

**Data plumbing**

- New typed client in `metatronui-kb/src/api/connections.ts`:
  ```ts
  getLatestSyncLog(connectionId, workspaceId): Promise<SyncLog | null>
  listSyncLogs(connectionId, workspaceId, limit=10): Promise<SyncLog[]>
  ```
- Both hit existing `GET /api/v1/dashboard/sync/history`. **Pre-flight check needed:** that endpoint currently takes `workspace_id` only; we need to confirm it supports a `connection_id` query parameter. If it does not, the fix is trivial (filter by `connection_id` in `dashboard_queries.get_sync_history`).

**Display — two layers**

*Inline summary (always shown):* in `ConnectionCard.tsx`, below the "Synced N ago" meta-line:

```
Last sync: ✅ 297 fetched · 12 new · 284 unchanged · 48 chunks · 6.2s
         (or) ❌ Sync failed: <error message> (2m ago)
         (or) ⏳ Running… (started 8s ago)    <- status='running'
```

Colors: `text-success` for success/partial, `text-error` for failed, `text-accent` for running. No new icon library dependencies — `Check`, `AlertCircle`, `Loader2` already imported.

*Optional "History" modal (same PR):* new `SyncHistoryModal.tsx`. Triggered by a small link/button next to the inline summary. Shows last 10 rows with timestamp, status, counts, duration, errors truncated to one line. Reuses existing `ConnectionDialog` styling. If review finds this too heavy for 309, we drop it — the inline summary alone closes the user-visible gap.

**Status transitions from "syncing" to runtime state.** Once Bug A is fixed, `connection.status` becomes reliable. The card can show a three-state badge — `syncing` → spinner; `active` → green dot; `error` → red with `error_message`. Current code already renders `StatusBadge` — we only need to trust it again.

### Error handling

- Insert of the initial `sync_logs` row uses `asyncio.to_thread(...)` wrapped in `try/except`. On failure we **still start the sync** (log a warning) — visibility is best-effort, we don't block the data path.
- Recovery on startup is non-fatal. Any DB error logs a warning and continues; the app must still come up.
- UI `getLatestSyncLog` surfaces errors via existing `apiFetch` toast plumbing. No dedicated error-retry loop.

## Testing

### Backend (metatron-core)

- `tests/unit/test_connections_sync.py` (new):
    - `test_trigger_sync_inserts_running_log` — after POST /sync, a `sync_logs` row exists with `status="running"` and matching connection_id. Background task is mocked out so we test the synchronous write path in isolation.
    - `test_sync_completion_updates_running_row` — run full `_run_connection_sync` with a stub connector returning 3 docs; assert exactly one `sync_logs` row transitions `running → success`.
    - `test_sync_failure_updates_running_row` — stub connector raises; assert row becomes `status="failed"`, `errors=[sanitized message]`, connection status → error.
- `tests/unit/test_sync_recovery.py` (new):
    - `test_recovery_running_logs_marked_failed` — seed one `running` row, run recovery, assert `failed` + duration set.
    - `test_recovery_syncing_connections_reset` — seed two connections `syncing`, run recovery, assert both `error` with expected message.
    - `test_recovery_idempotent` — running recovery twice does not double-modify already-failed rows.
    - `test_recovery_db_error_does_not_block_startup` — patch `PostgresStore` to raise; assert log warning, no re-raise.

No `make eval` impact — search pipeline untouched.

### Frontend (metatronui-kb)

- Jest/Vitest: stub `getLatestSyncLog` → `null | running | success | failed` → assert `ConnectionCard` renders the four expected strings and CSS classes.
- Manual Playwright smoke (done before the PR): trigger a Jira sync locally, watch card transition `running → success` with live counts, confirm retry button unblocks.

### Integration acceptance (manual on local stack)

1. Reset both currently-stuck connections via the startup recovery (restart API, confirm `status='error'`).
2. Hit Sync in UI — card shows "Running…", Sync button disabled by `status='syncing'`.
3. After sync completes — card shows "✅ N fetched · M new · …", Sync button re-enabled.
4. Force a failure (bad API token) — card shows "❌ Sync failed: <error>", `error_message` populated, Sync button re-enabled.
5. Kill API mid-sync, restart — card shows "❌ Sync interrupted (API restart)", last `sync_logs` row is `failed`.

## Files Touched

### Core (`metatron-core`)

- `src/metatron/api/routes/connections.py` — restructure `trigger_sync` + `_run_connection_sync` (write initial row, UPDATE on finish).
- `src/metatron/storage/postgres.py` — add `create_sync_log(workspace_id, connection_id, connector_type, sync_id) -> None` and `update_sync_log(sync_id, **fields) -> None` helpers; centralize SyncLogRow writes (removes the inline ORM in `connections.py`).
- `src/metatron/storage/dashboard_queries.py` — confirm / add `connection_id` filter to `get_sync_history`.
- `src/metatron/api/app.py` — invoke recovery in lifespan.
- `src/metatron/storage/recovery.py` (new) — `recover_interrupted_syncs(engine) -> dict` (returns counts).
- `tests/unit/test_connections_sync.py`, `tests/unit/test_sync_recovery.py` — new tests.

### UI (`metatronui-kb`)

- `src/api/connections.ts` — add `SyncLog` type and `getLatestSyncLog` / `listSyncLogs`.
- `src/hooks/useSyncLogs.ts` (new) — react-query wrapper, polls while `connection.status==='syncing'`.
- `src/components/sources/ConnectionCard.tsx` — inline "Last sync" summary; swap toast from "Sync started" to show the sync_id/row for immediate feedback.
- `src/components/sources/SyncHistoryModal.tsx` (new, optional) — history modal.

No new deps on either side.

## Rollout

- Backend PR first, merged to `develop`, auto-deployed to local stack. Run startup recovery once — stuck connections clear.
- UI PR depends on backend `connection_id` filter in sync history endpoint; verify once backend is live.
- No config / env flag needed. Behavior change is strictly additive for users.

## Open Questions

1. **Jira title says "not ingested in memory"** — do we want to double-check Qdrant actually holds the 297 chunks (vs. just PG reporting `qdrant_synced=true`)? One `scroll` call confirms it. Cheap but we haven't done it yet; worth doing during implementation as a sanity step.
2. **History modal: in this ticket or follow-up?** Default in this design is: include it. If the reviewer pushes back, drop it — inline summary alone closes the user-visible complaint.
3. **Watchdog for runaway `running` rows.** Not in this PR; called out so reviewers don't flag the omission.
