# knowledge/

Phase 2 (2026-05-13) — the `/api/v1/knowledge/records` endpoint gained a `lifetime=persistent|session|all` query param (default `persistent`). KB rows always have `session_id=None`, `ttl_expires_at=None`. The `lifetime` filter applies only to the agent (memory) leg; the KB leg ignores it.

## Purpose
L3 read-only facade over `raw_documents`. Paired with `memory/service.py` to back the unified
`GET /api/v1/knowledge/records` endpoint that merges agent memory records and KB documents
in the Memory Inspector. See `docs/superpowers/2026-05-12-memory-scopes-audit.md` for context.

## What this module is
- `service.py` — `RawDocumentReadService`: list and count `raw_documents` rows filtered by
  `workspace_id`. Called by the `knowledge` API route to provide the KB leg of the unified view.

## What this module is NOT
- Not a writer — no inserts, updates, or deletes to any table
- Not a bridge to `memory_records` — the two sources are kept separate at storage; merging
  happens only at the view layer (`/api/v1/knowledge/records`)
- Not a place for ingestion logic — ingestion lives in `ingestion/`
- Not a place for freshness logic — freshness lives in `freshness/` and `ingestion/freshness/`

## Layer rules
- Layer: L3 (services)
- May import from: `core/` (L0), `storage/` (L1)
- Must NOT import from: `api/`, `agent/`, `channels/`, `retrieval/`, `ingestion/`, `memory/`

## `origin` field
`origin` is endpoint-derived — the value `"agent"` or `"kb"` is assigned by the API route
based on which source returned the row. It is NOT stored in `raw_documents` or `memory_records`.
Do NOT propose adding an `origin` column to either table.

## Planned work
Later memory-scopes phases will introduce orthogonal `visibility / lifetime / kind` axes on
`memory_records`. This module stays read-only on the KB side regardless of those changes.
Phase 3 details live in `docs/superpowers/2026-05-12-memory-scopes-audit.md` (local, gitignored).
