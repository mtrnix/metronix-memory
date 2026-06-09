# Autosync architecture & default-on policy (MTRNIX-396)

Connections can carry a `sync_cron` schedule that drives recurring **Autosync** of their
source (cron, interpreted in a single deployment-wide timezone, default UTC). This ADR records
two non-obvious decisions about *how* that runs and *what happens out of the box*.

## Decision 1 — in-process scheduler, not a separate worker

The scheduler is an asyncio loop started in the API process lifespan (`api/autosync.py`),
**not** a dedicated worker process. This deliberately diverges from the freshness pipeline,
which runs as a standalone process (`python -m metatron.memory.freshness`) with Redis-based
queueing, heartbeats, and orphan reclaim.

Why the divergence: the sync work (`_run_connection_sync`) already lives in the API layer and
pulls in the connector registry, Fernet decryption, and the ingestion pipeline. Reusing it from
a separate process would force extracting it into a service layer — real refactoring for an MVP.
Multi-replica safety is instead bought cheaply with an **atomic claim**: the scheduler advances
`connections.next_run_at` and sets `status='syncing'` in a single conditional `UPDATE … RETURNING`,
and only spawns the sync if it won the row. At most one replica fires each scheduled run, and this
also closes the pre-existing race in the manual sync path. Per-tick concurrency is bounded by
`METATRON_AUTOSYNC_MAX_CONCURRENT` (default 2); bursts (e.g. many connections due at 03:00) spread
across ticks because un-claimed rows stay due.

Consequence: autosync only runs where the API runs, and a long-down API misses schedules until it
comes back (then fires **once** — coalesce-to-one, not replay). Promoting the scheduler to a
freshness-style separate process later is additive and does not require a data migration.

## Decision 2 — autosync is ON by default, including for existing connections

`connections.sync_cron` has `server_default '0 3 * * *'`, so every **new connector** autosyncs
nightly at 03:00 unless the user clears or changes the schedule. The introducing migration also
**backfills existing connector rows** to `0 3 * * *`. Channels (telegram/discord/slack) get `NULL`
— they have no sync — and the scheduler defensively skips non-connectors.

Why: for a knowledge base, freshness-by-default is the desired behaviour, not a surprise — a KB
nobody re-syncs goes stale silently. Making autosync opt-in would leave most connections never
refreshed.

Consequence to be aware of: the deploy that ships this migration silently enables nightly
background syncs for all pre-existing connectors. This is intentional. The master switch
`METATRON_AUTOSYNC_ENABLED` (default `true`) turns the whole loop off if an operator needs to.

**Initial sync on create.** A newly created connector is stamped `next_run_at = NULL`, which the
scheduler treats as "due now" — so it syncs on the next tick rather than waiting until the first
03:00. Backfilled existing rows are likewise `next_run_at = NULL`, so new and pre-existing
connectors behave identically on first run. Editing an existing connection's `sync_cron` is
treated as schedule tuning, not a sync request, so an update computes the next occurrence
(`next_run_at = next cron time`) rather than firing immediately.

## Considered and rejected

- **Interval-in-minutes instead of cron** — rejected; cron expresses "nightly at 03:00", which is
  the intended default, without a separate "time of day" concept.
- **Per-connection timezone** — rejected for MVP; one tenant ≈ one timezone, so a single
  `METATRON_AUTOSYNC_TIMEZONE` knob suffices. Upgrade to per-connection is additive.
- **Driving "due" off `last_synced_at`** — rejected; it only advances on success, so a failing
  connector would re-fire every tick. `next_run_at`, advanced at claim time, decouples schedule
  cadence from the sync cursor.
