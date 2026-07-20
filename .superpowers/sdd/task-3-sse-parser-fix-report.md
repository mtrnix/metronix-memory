# Task 3 SSE Parser Fix Report

## Status

Fixed the final-review Important issue: conversation capture now buffers raw
transport chunks until a complete SSE event is framed before decoding assistant
content or usage.

## Implementation

- Added `_SseEventParser`, which accepts arbitrary byte chunks and emits data
  payloads only after a blank LF or CRLF SSE event delimiter.
- `_SseCompletionDetector` uses the same parser, so a terminal `data: [DONE]`
  remains recognized only after the complete framed event arrives.
- The proxy still yields every upstream chunk unchanged before feeding it to the
  parser. Capture is still scheduled only after a successful 2xx stream has
  yielded a complete terminal marker.
- Added a regression test that splits a CRLF-framed assistant JSON event inside
  its object, verifies the client receives identical bytes, and verifies the
  persisted assistant event contains the complete `split answer` text.

## Verification

- RED: `uv run pytest -q tests/unit/test_proxy_service_proxy_mode.py -k split_across_chunks`
  failed before the implementation because only the user event was captured.
- GREEN: the same regression passed after the implementation (`1 passed`).
- `POSTGRES_PORT=5433 uv run pytest -q tests/unit/test_proxy_service_proxy_mode.py tests/integration/api/test_proxy_e2e.py tests/integration/api/test_conversation_compaction.py`
  passed (`9 passed`).
- `uv run ruff check src/ tests/` passed.
- `uv run ruff format --check src/ tests/` passed (`673 files already formatted`).
- `uv run mypy src/metronix/proxy/service.py` passed.
- `git diff --check` passed.

## Concerns

- Repository-wide `uv run mypy src/metronix/` remains a pre-existing baseline
  failure: 3,119 errors across 111 files (for example, missing third-party
  stubs and unrelated strictness violations). The changed proxy module itself
  is type-clean.
- The focused API run emitted existing Qdrant compatibility and
  `datetime.utcnow()` deprecation warnings; neither originates in this change.
