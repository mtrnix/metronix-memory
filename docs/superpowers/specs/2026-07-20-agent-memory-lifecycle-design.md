# Agent Memory Lifecycle Design

## Status

Approved design. This specification covers general conversational agents and is
the prerequisite for implementation planning.

## Goals

1. Compact long conversational sessions without losing durable user context.
2. Retain raw conversation events only temporarily; retain compacted,
   source-linked summaries as the durable default.
3. Keep durable memories private to the originating agent unless explicitly
   promoted to a shared scope.
4. Provide disaster-recovery backups, Time-Machine-style memory history, and
   portable migration to other agent platforms.

## Non-goals

- Capturing or retaining raw conversations indefinitely by default.
- Training a learned memory-management policy in the initial release.
- Replacing the existing PostgreSQL, Qdrant, Neo4j, Redis, freshness, or MCP
  abstractions.
- Treating a database backup as a user-facing memory-history feature.

## Product model

Memory is represented at three layers.

1. **Temporary event buffer.** Raw user turns, assistant turns, and tool
   events are retained for a configurable period. Supported policies are
   `24h`, `7d`, `30d`, and `forever`; the default is `7d`.
2. **Session ledger.** A compact structured summary captures the outcome of a
   topical conversation segment: people and entities, decisions, commitments,
   corrections, unresolved threads, and next follow-ups.
3. **Durable agent memory.** Atomic facts, preferences, pins, commitments,
   relationship links, and synthesized profiles are stored with provenance.
   They are private (`per_agent`) by default.

The event buffer is the only layer that contains raw turn text. Expiry removes
the text and leaves only non-reversible provenance metadata such as the source
session id, time range, content hash, extraction version, and confidence.

## Compaction controller

The first implementation is deterministic and feature-flagged. It runs when
one of the following occurs:

- the configured token/event budget is reached;
- a session ends or has been inactive for a configured period;
- a client explicitly requests compaction; or
- a future focus API closes a topical work block.

The controller produces a session ledger and candidate memory writes. It must
not persist raw transcript fragments as durable memories.

### Ledger schema

Each ledger contains:

- `goal_or_topic`
- `participants` and entity references
- `decisions`
- `commitments` with owner, status, and optional due date
- `preferences`
- `facts`
- `corrections` and supersession references
- `open_threads`
- `next_follow_ups`
- source event range, source hashes, extractor version, confidence, and
  created timestamp

### Write policy

Explicit user instructions to remember something may be written directly as
active records after validation. Inferred records are written as `candidate`
and enter the existing review/freshness lifecycle. The automatic write policy
is fail-closed: it rejects secrets, credential-like values, sensitive data
without explicit future policy support, temporary chatter, and instructions
embedded in untrusted content.

Corrections create a candidate relation to the prior memory and request
supersession or archival rather than silently creating contradictory active
facts.

### Context assembly

The prompt assembler receives a small always-on profile/preference section,
the current session ledger, and query-relevant durable memories. Raw event
text is never injected after compaction unless an explicitly authorized
temporary-session retrieval path is used.

## Sharing and deletion

- Durable memory defaults to `per_agent`.
- Sharing is an explicit promotion operation, with actor, time, source record,
  and target scope recorded in provenance.
- Deletion emits a durable tombstone. Tombstones are exported and imported so a
  target platform cannot accidentally revive erased or superseded memories.
- Deleting a temporary event buffer must not delete its already-approved
  compacted artifacts; deleting a durable artifact must preserve a minimal
  tombstone for synchronization unless the privacy-erasure policy requires
  total removal.

## Backup and restore

`metronix backup` is a disaster-recovery interface, separate from Time
Machine. Each backup is a dated directory or archive with a signed manifest,
checksums, component versions, timestamps, and restore status.

It contains:

- PostgreSQL logical dump as the authoritative data copy;
- Qdrant collection snapshots for rapid vector recovery;
- Neo4j dump for relationship recovery;
- optional Redis RDB/AOF data for temporary sessions and queues;
- existing snapshot files; and
- encrypted application configuration, excluding secrets by default.

Commands:

```text
metronix backup create
metronix backup verify <bundle>
metronix backup restore <bundle> --into <isolated-target>
```

Restore always targets an isolated environment first, verifies checksums and
record counts, and requires a separate explicit cutover. No backup command may
overwrite an existing backup artifact.

## Time Machine

Time Machine is a user-facing history service for compacted durable memory.

- Capture a checkpoint before destructive writes and restores, and on a
  schedule.
- Store periodic immutable base snapshots plus content-addressed deltas.
- Retain hourly, daily, weekly, and monthly checkpoints according to policy.
- Provide timeline listing, diff, preview, restore-one-record,
  restore-agent, and restore-as-new-agent operations.
- Every restore automatically creates a pre-restore checkpoint.
- Verify retained checkpoints periodically and surface unreadable artifacts.

The existing per-agent JSONL+gzip snapshot format remains a compatible base
artifact. The Time Machine index adds scheduling, retention, delta chains, and
safe restore/fork behavior.

## Portable Agent Memory Bundle

The Agent Memory Bundle (`.amb`) is the canonical, versioned interchange
format for compacted memory migration. It is a gzip-compressed archive of JSON
and JSONL files with a checksum manifest:

```text
manifest.json
profiles.json
memories.jsonl
session_summaries.jsonl
commitments.jsonl
relationships.jsonl
tombstones.jsonl
checksums.sha256
```

The bundle contains no expired raw transcript text. Source links carry session
identifier, timestamp range, source hash, and extraction version only.

Initial adapters, in order:

1. Agent Memory Bundle round-trip within Metronix.
2. Generic JSONL and Markdown export/import.
3. `MEMORY.md` and project-note rendering for file-oriented agents.
4. Codex, Claude Code, and Hermes mapping adapters.

An import defaults to `per_agent`, preserves tombstones, and writes records as
`candidate` when required provenance is absent. It never overwrites live
memory without an explicit merge policy.

## API and operational boundaries

New public surfaces should be additive:

- session event write/list/expire APIs;
- session compact and ledger read APIs;
- Time Machine timeline/diff/preview/restore APIs;
- backup create/verify/restore CLI commands; and
- Agent Memory Bundle export/import CLI and REST endpoints.

All write APIs must require workspace and agent identity, preserve current
workspace isolation, and record an activity event. Feature flags gate automatic
compaction, event retention, scheduled Time Machine checkpoints, and external
import/export.

## Verification

Implementation must add integration coverage for:

- token/session-triggered compaction and feature-disabled behavior;
- secret/prompt-injection rejection and correction supersession;
- event expiry with durable source-linked summaries intact;
- per-agent isolation and explicit sharing promotion;
- backup create, verify, isolated restore, and component checksum failure;
- Time Machine delta reconstruction, retention, preview, fork, and reversible
  restore; and
- Agent Memory Bundle round-trip, tombstone preservation, and safe import
  merge behavior.

Evaluation should measure factual recall, correction handling, retrieval
precision, compaction token reduction, and privacy-policy false positives and
false negatives. It must run without an external LLM by using fixture extractors
and deterministic policy test cases.

## Delivery order

1. Temporary event buffer, deterministic compaction controller, policy gate,
   and ledger persistence.
2. Portable Agent Memory Bundle and generic JSONL/Markdown adapters.
3. Time Machine index, retention, delta checkpoints, and safe restore/fork.
4. Full-system backup CLI and automated restore verification.
5. Platform-specific adapters and optional agent-controlled focus API.
6. Evaluate whether learned memory management is justified by production data.

## Delivery tracking

| Delivery wave | GitHub issue | Dependencies |
| --- | --- | --- |
| Conversation compaction foundation | #343 | #344 for automatic-write policy; #345 and #346 are follow-up quality work |
| Portable Agent Memory Bundle | #347 | #343, #344 |
| Memory Time Machine | #348 | durable compaction records from #343 |
| Full-system disaster-recovery backups | #349 | independent of Time Machine; shares snapshot artifacts |
