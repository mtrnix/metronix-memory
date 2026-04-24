# Memory MCP — Follow-up Tasks

Deferred items from **MTRNIX-314** (Memory MCP lifecycle-status filter + review queue
tools, merged 2026-04-22, PR #86). Captured here rather than filed as Jira tickets so
the team can triage together before committing.

## 1. Admin-only `memory_force_delete` MCP tool

**Scope:** a new MCP tool that performs the hard-delete path currently missing from
the MCP surface.

**Why:** `memory_review_resolve(action="discard")` is intentionally soft —
`status → ARCHIVED` with `verification_state="discarded_via_review"`. The PG row and
its Qdrant/Neo4j mirrors stay in place. We accepted this trade-off in MTRNIX-314 because
destructive ops on MCP (bearer-token auth, external network transport) is too sharp a
default. But there is no way today to hard-delete via MCP — the only admin path is
`DELETE /api/v1/memory/{id}` over REST.

**Sketch:**
- New tool `metatron_memory_force_delete(record_id, workspace_id, reason)`.
- Same audit-trail obligations as `resolve_review`: `MachineEvent` with
  `event_type="memory_force_deleted"`, `FRESHNESS_*` event on EventBus when wired.
- MCP bearer-token auth is not enough — should be gated on the future 5-role RBAC
  (Agent Admin / Super Admin) once that lands. Until then: keep it out of MCP
  entirely, or require a separate `METATRON_MCP_DESTRUCTIVE_KEY` env gate.
- Deletes: PG row (`memory_records`), Qdrant point, Neo4j `:MemoryRecord` node + all
  relationship edges, Redis session cache entries matching the id.

**Blocked by:** the RBAC migration plan (below) — without it, there is no
authorization story strong enough to justify adding destructive ops to MCP.

## 2. Content / tag auto-merge on `merge_into:<id>`

**Scope:** extend `MemoryService.resolve_review` so that `action="merge_into:<id>"`
optionally merges the current record's `content`, `tags`, and `importance_score`
into the target record before marking the current record SUPERSEDED.

**Why:** today `merge_into` sets `status=SUPERSEDED` + `superseded_by=<id>`, leaving
the target record untouched. That loses information — the reason the review queue
flagged a duplicate pair is often that the two records complement each other.

**Design questions to close first:**
- Union vs. replacement for tags? Union feels right but inflates tag cardinality.
- Content merge: append with a separator, or leave target untouched and store the
  merged content in a new `merged_from` JSONB field on the target for audit?
- Importance score: `max(current, target)`, weighted average, or leave target?
- Re-embedding: any content change on the target triggers a Qdrant re-embed. That
  is a real cost — estimate per-workspace before flipping this on.

**Related:** there is no UX for reviewing the merged result before the transaction
commits. Control Center is the natural place for that; punt on exposing this via
MCP until CC has a review UI.

## 3. 5-role RBAC gating of `memory_review_resolve`

**Scope:** gate destructive review actions behind the future 5-role RBAC model.

**Current state:** MCP bearer-token is the only auth at MCP layer. REST API has
a 3-role model (viewer / editor / admin). The 5-role target — Viewer / Editor /
Agent Admin / Company Admin / Super Admin — is still a planning-stage concern
across the repo (see root CLAUDE.md "Do NOT" section). When it lands:
- `memory_review_list` → viewer+
- `memory_review_resolve` for `keep` / `archive` → editor+
- `memory_review_resolve` for `merge_into` / `discard` → Agent Admin+
- Future `memory_force_delete` → Agent Admin or Super Admin only

**Why not now:** forcing a role split on MCP today would require inventing a
per-agent role claim system that does not exist yet. Wait for the broader RBAC
migration rather than building a one-off for this tool.

## Open question — should any of these be filed as tickets now?

The default answer is probably "maybe #1, not #2/#3":

- **#1** becomes interesting only when an ops team starts hitting ARCHIVED-record
  pile-up. Defer until there is a concrete request.
- **#2** is UX speculation — wait for Control Center.
- **#3** blocks on the broader RBAC migration — file it there, not as a standalone.
