# Final Fix Report — upload workspace isolation + RBAC + PG pool leak

Date: 2026-06-22
Branch: feat/upload-via-connector-pipeline

---

## C1 — Workspace isolation bypass on `/upload` alias

**Finding:** `POST /api/v1/upload` accepted `workspace_id: str | None = Form(None)` and
used it verbatim via `ws = workspace_id or resolve_workspace_id(request)`. A caller could
write documents into any workspace by supplying a different workspace_id in the form body,
bypassing the JWT access check that `resolve_workspace_id` enforces.

**Fix:**
- `src/metatron/api/routes/chat.py:248-251` — removed `workspace_id: str | None = Form(None)`
  parameter entirely.
- `src/metatron/api/routes/chat.py:265` — now unconditionally calls
  `ws = resolve_workspace_id(request)`, which only accepts an override via the
  `?workspace_id` query parameter (access-checked against JWT claims).

---

## I2 — Missing RBAC on `/upload` alias + hardcoded user_id

**Finding:** The alias had no auth dependency (`require_editor` or equivalent), meaning any
unauthenticated caller could ingest documents. It also had `user_id: str = Form("user")` as a
caller-controlled string, allowing caller attribution spoofing.

**Fix:**
- `src/metatron/api/routes/chat.py:15` — added import for `Depends` from fastapi.
- `src/metatron/api/routes/chat.py:16` — added import `from typing import Annotated`.
- `src/metatron/api/routes/chat.py:17` — added imports `from metatron.auth.dependencies import
  require_editor` and `from metatron.core.models import User`.
- `src/metatron/api/routes/chat.py:250` — replaced `user_id: str = Form("user")` and
  `workspace_id: str | None = Form(None)` with
  `user: Annotated[User, Depends(require_editor)]` (exact pattern from `files.py`).
- `src/metatron/api/routes/chat.py:266` — `user_id = getattr(user, "id", "user")` derived
  from the authenticated user, not caller-controlled.
- `Form` import removed from the `chat.py` fastapi import line (was only used in the fixed
  params; verified no other usage in the file).

**Param ordering note:** `user` (no default) placed before `file: UploadFile = File(...)`
(has default) to satisfy Python's non-default-follows-default rule while keeping the same
FastAPI DI semantics as `files.py`.

---

## I1 — PostgresStore connection-pool leak

**Finding:** Both `_ingest_uploads` and `_background_sync` in `files.py` create a
`PostgresStore` instance but never close it. Each `PostgresStore.__init__` creates a
SQLAlchemy async engine with a connection pool. Abandoned pools leak file descriptors and
DB connections on every upload request.

**PostgresStore.close() verification:** `src/metatron/storage/postgres.py:1523` —
`async def close(self) -> None:` — confirmed present and async.

**Fix:**
- `src/metatron/api/routes/files.py:88-92` — wrapped `persist_raw_documents` call in
  `try/finally` with `await store.close()`.
- `src/metatron/api/routes/files.py:104-117` — added `finally: await store.close()` to
  `_background_sync`, preserving the existing `except Exception` warning log.

---

## Test changes

Both stub stores in `test_files_routes.py` and `test_upload_alias.py` gained an
`async def close(self) -> None: pass` method to satisfy the new `await store.close()`
calls.

`test_api.py::TestUpload::test_upload_text_file` — removed stale
`data={"user_id": "u1", "workspace_id": "TEST_WS"}` form fields that no longer exist
on the alias endpoint. The `_ingest_uploads` mock is still patched so no real workspace
logic runs; the `upload_client` fixture injects `DEFAULT_WORKSPACE_ID="TEST_WS"` so
`resolve_workspace_id` returns the correct value.

---

## Test run

```
pytest tests/unit/test_files_routes.py tests/unit/test_upload_alias.py \
       "tests/unit/test_api.py::TestUpload" -v

7 passed, 27 warnings in 2.68s
```

---

## Lint (`ruff check` on touched files)

4 issues found, all pre-existing before this change (verified via `git stash`):
- `TC003` — `AsyncGenerator` not in TYPE_CHECKING block (pre-existing)
- `N806` x2 — `MAX_HISTORY_CHARS` uppercase variable in function (pre-existing)
- `B008` — `File(...)` in argument default (pre-existing)

Zero new issues introduced.

---

## Typecheck (`mypy` on touched files)

1 pre-existing error: `var-annotated` at `chat.py:64` for `history_lines` (confirmed
pre-existing via `git stash`). Zero new errors.

---

## Concerns

None. All three fixes are contained to the two route files + test stubs. No interface
changes, no migration, no new config vars.
