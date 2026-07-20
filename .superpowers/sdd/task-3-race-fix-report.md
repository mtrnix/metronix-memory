# Task 3 Automatic Compaction Race Fix Report

## Final status

Complete. Capture-triggered automatic compaction is disabled even when
`METRONIX_CONVERSATION_COMPACTION_ENABLED=true`. Capture still persists events
after a successful SSE stream, the expiry worker remains opt-in, and explicit
authenticated `POST /api/v1/conversations/{session_id}/compact` remains
available.

## Implementation commit

`fe5a69f fix: disable unsafe automatic conversation compaction`

## Verification

- Red: `uv run --extra dev pytest tests/unit/test_proxy_service_proxy_mode.py -q`
  failed before the fix because the enabled-flag regression test observed one
  `maybe_compact()` call.
- Green: `uv run --extra dev pytest tests/unit/test_proxy_service_proxy_mode.py tests/unit/memory/test_compaction.py tests/integration/api/test_conversation_compaction.py -q`
  passed: 11 tests.
- `uv run --extra dev ruff check src/metronix/proxy/service.py src/metronix/core/config.py tests/unit/test_proxy_service_proxy_mode.py`
  passed.
- `uv run --extra dev ruff format --check src/metronix/proxy/service.py src/metronix/core/config.py tests/unit/test_proxy_service_proxy_mode.py`
  passed.
- `git diff --check` passed.
- `uv run --extra dev mypy src/metronix/` remains blocked by the existing
  repository baseline (3,119 errors in 111 files). The scoped command also
  reports 109 pre-existing `Settings()` constructor diagnostics at the
  unchanged settings-cache call in `src/metronix/core/config.py:611`.

## Concerns and follow-up

- The focused integration test passed with one existing `datetime.utcnow()`
  deprecation warning.
- Automatic compaction must remain unavailable until
  `ConversationPostgresStore` gains a durable, cross-process atomic
  per-session claim/acknowledgement API. A process-local lock would not meet
  that requirement.
