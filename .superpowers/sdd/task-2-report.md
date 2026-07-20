# Task 2 Report: Policy-Gated Deterministic Compaction

## Scope

Implemented the GitHub #343 Task 2 controller, deterministic policy gate,
settings, and `MemoryService` persistence bridge. Proxy capture, API routes,
context injection, expiry scheduling, and a background worker remain outside
this task.

## Files

- `src/metronix/memory/compaction_policy.py`
  - Adds `MemoryCandidate`, `Decision`, and a deterministic fail-closed policy.
  - Reuses the Task 1 safety validation for credentials and untrusted embedded
    instructions; rejects temporary chatter without logging the rejected text.
  - Explicit candidates become `active`; inferred candidates become `candidate`.
- `src/metronix/memory/compaction.py`
  - Adds `CompactionController`, `CompactionResult`, and
    `DeterministicFixtureExtractor`.
  - Persists hash-only, structured ledgers and policy-approved candidates.
  - `maybe_compact()` is event-budget gated and returns without reading events
    when automatic compaction is disabled.
- `src/metronix/core/config.py`
  - Adds disabled-by-default automatic compaction, seven-day raw event
    retention, event-budget, and idle-period settings.
- `src/metronix/memory/service.py`
  - Adds `save_compaction_memory()`, which repeats Task 1 content validation,
    requires canonical SHA-256 provenance, writes `MemoryScope.PER_AGENT`, and
    relies on the existing explicit `promote()` path for broader scopes.
- `tests/unit/memory/test_compaction.py`
- `tests/unit/memory/test_compaction_policy.py`

## Design choices

- The default deterministic extractor emits no candidates from raw transcript
  text. Tests and future extractors provide structured `MemoryCandidate`
  inputs, which are policy-checked before any durable write.
- Ledger summaries contain schema keys, counters, extractor version, and source
  hashes only. They intentionally omit raw event content and caller-provided
  compaction reasons.
- Explicit `compact()` calls are permitted while automatic compaction remains
  disabled; only `maybe_compact()` observes the automatic feature flag.

## TDD and verification

Red test run before implementation:

```text
uv run --extra dev pytest tests/unit/memory/test_compaction.py tests/unit/memory/test_compaction_policy.py -q
ModuleNotFoundError: No module named 'metronix.memory.compaction'
ModuleNotFoundError: No module named 'metronix.memory.compaction_policy'
```

Final checks:

```text
uv run --extra dev pytest tests/unit/storage/test_conversation_postgres_safety.py tests/unit/memory/test_compaction.py tests/unit/memory/test_compaction_policy.py -q
22 passed in 0.95s

uv run --extra dev ruff check src/metronix/memory/compaction.py src/metronix/memory/compaction_policy.py src/metronix/core/config.py src/metronix/memory/service.py tests/unit/memory/test_compaction.py tests/unit/memory/test_compaction_policy.py
All checks passed!

uv run --extra dev ruff format --check src/metronix/memory/compaction.py src/metronix/memory/compaction_policy.py src/metronix/core/config.py src/metronix/memory/service.py tests/unit/memory/test_compaction.py tests/unit/memory/test_compaction_policy.py
6 files already formatted

uv run --extra dev mypy --follow-imports=skip src/metronix/memory/compaction.py src/metronix/memory/compaction_policy.py
Success: no issues found in 2 source files
```

`mypy` over `config.py` and `service.py` still reports the repository's
pre-existing strict-Pydantic constructor/import errors; the focused new modules
are type-clean.

## Commit

This report is included in `feat: add policy-gated conversation compaction`.
Use `git log -1 --oneline` for its final revision after the report amend.

## Concerns

- `ConversationPostgresStore` currently exposes `list_uncompacted()` but no
  acknowledgment/mark-compacted write method. Task 2 therefore does not change
  raw-event state; Task 3 should mark successfully compacted events before
  enabling automatic scheduling, so future triggers do not reprocess them.
