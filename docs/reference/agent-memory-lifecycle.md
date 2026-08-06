# Agent Memory Lifecycle

This reference describes the architecture and safety contract for Metronix
conversation compaction and durable agent memory.

## Lifecycle

Metronix separates conversational memory into three layers:

1. **Temporary event buffer.** Raw user and assistant turns are held only long
   enough to build a compacted result. Retention choices are `24h`, `7d`,
   `30d`, and `forever`; the default is `7d`.
2. **Session ledger.** A compact, source-linked record of a completed session
   segment. It retains only structured metadata and source hashes, never raw
   conversation text.
3. **Durable agent memory.** Facts, preferences, pins, commitments, and other
   reviewed records. Durable records are private to their originating agent
   (`per_agent`) unless explicitly promoted.

When temporary events expire, the raw content is deleted while the ledger's
non-reversible provenance remains available.

## Conversation compaction

The current compaction foundation is deterministic and does not require an
external LLM. It uses a fail-closed policy before either temporary or durable
content is persisted:

- secrets, credential-like values, and untrusted instruction content are
  rejected;
- durable provenance is restricted to canonical SHA-256 source hashes;
- inferred records are written as candidates; and
- explicit sharing is a separate promotion operation.

The context assembler can inject a numeric-only session-ledger section into a
prompt. It never injects raw conversation events.

Explicit, authenticated session compaction uses a database-backed
claim/finalize lifecycle. A claimed batch is marked compacted only after its
ledger and candidate writes complete; failed work is released for a later
retry. This prevents concurrent explicit requests from processing the same
batch.

Capture-triggered automatic compaction remains disabled, including when its
feature setting is enabled. It will stay disabled until the event store has a
renewable, cross-process-safe claim contract suitable for long-running
extraction.

## Sharing and deletion

- Promotion records the actor, time, source record, and target scope.
- Corrections should supersede or archive prior records rather than silently
  creating contradictory active facts.
- Deleting a durable record creates a tombstone for synchronization unless a
  stricter privacy-erasure policy requires total removal.

## Planned capabilities

The following work is tracked separately and is not part of the current
conversation-compaction implementation:

- Portable Agent Memory Bundle migration (#347).
- Time-Machine-style history for durable memory (#348).
- Full-system disaster-recovery backups (#349).

These capabilities must exclude expired raw transcripts by default, preserve
workspace and agent isolation, and support safe, verifiable restore or import
workflows.

## Operational requirements

All memory write APIs require workspace and agent identity and emit an activity
event without recording rejected content. Feature flags gate raw-event
retention, automatic compaction, scheduled checkpoints, and import/export.

Tests for lifecycle changes must run without an external LLM and cover event
expiry, secret and prompt-injection rejection, agent isolation, and
source-linked durable records.
