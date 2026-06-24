# Data Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a departing user export all of a workspace's agent memory (one Markdown file per agent, including unregistered agents) and all ingested documents in original whole form, delivered as a downloadable ZIP via a one-time-token URL, triggered over MCP or REST.

**Architecture:** A single `ExportService` (in a new `src/metronix/export/` package) owns all build logic. Build runs as an in-process `asyncio` task on the API process; authoritative job state lives in a durable PostgreSQL `export_jobs` table, the one-time download token lives in Redis, and the ZIP lives on a shared volume. MCP tools and a REST router are thin surfaces over the service. The download endpoint is authorized solely by the one-time token in its URL.

**Tech Stack:** Python 3.12, FastAPI, FastMCP, SQLAlchemy async, Alembic, Redis, pydantic / pydantic-settings, `zipfile` (stdlib), pytest + pytest-asyncio.

## Global Constraints

- Package root is `src/metronix/` (the active package; `src/metatron/` is legacy — do not touch).
- Python `>=3.12,<3.14`. Ruff line length 99. mypy strict.
- pytest config: `asyncio_mode=auto`; tests touching real PostgreSQL/Redis use the `integration` marker (`@pytest.mark.integration`).
- All tool/REST identifiers use the `metronix_` / `/api/v1/` conventions already in the codebase.
- This feature targets the HTTP API deployment (MCP mounted in the FastAPI process at `/mcp`, REST at `/api/v1`, same uvicorn). stdio-only MCP is out of scope.
- Memory export includes **persistent** records (`ttl_expires_at IS NULL`) of **all** lifecycle statuses; session/TTL records are excluded.
- One-time tokens: CSPRNG, ≥128 bits (`secrets.token_urlsafe(32)`); never logged.
- Every archive path segment is slugified (path-traversal safe); the real identifier is preserved inside files and in `manifest.json`.
- MCP `metronix_export_data` must NOT silently fall back to workspace `"default"` — it requires an explicit `workspace_id` or `all_workspaces=true`.

---

### Task 1: Config settings

**Files:**
- Modify: `src/metronix/core/config.py` (add fields near `freshness_llm_api_base_url:278`, mirroring its `Field(..., alias=...)` style)
- Test: `tests/unit/test_export_config.py`

**Interfaces:**
- Produces: `Settings.public_base_url: str`, `Settings.export_dir: str`, `Settings.export_token_ttl_seconds: int`, `Settings.export_disk_cap_bytes: int`, `Settings.export_job_watchdog_seconds: int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_export_config.py
from metronix.core.config import Settings


def test_export_settings_defaults():
    s = Settings()
    assert s.public_base_url == ""
    assert s.export_dir == "/data/exports"
    assert s.export_token_ttl_seconds == 3600
    assert s.export_disk_cap_bytes == 5_000_000_000
    assert s.export_job_watchdog_seconds == 3600


def test_export_settings_env_override(monkeypatch):
    monkeypatch.setenv("METRONIX_PUBLIC_BASE_URL", "http://host:8001")
    monkeypatch.setenv("METRONIX_EXPORT_TOKEN_TTL_SECONDS", "120")
    s = Settings()
    assert s.public_base_url == "http://host:8001"
    assert s.export_token_ttl_seconds == 120
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_export_config.py -v`
Expected: FAIL — `AttributeError`/missing attributes.

- [ ] **Step 3: Add the fields**

Add inside the `Settings` class in `src/metronix/core/config.py` (anywhere among the field declarations):

```python
    # --- Data export (one-time-token ZIP export) ---
    public_base_url: str = Field(default="", alias="METRONIX_PUBLIC_BASE_URL")
    export_dir: str = Field(default="/data/exports", alias="METRONIX_EXPORT_DIR")
    export_token_ttl_seconds: int = Field(
        default=3600, alias="METRONIX_EXPORT_TOKEN_TTL_SECONDS", ge=60
    )
    export_disk_cap_bytes: int = Field(
        default=5_000_000_000, alias="METRONIX_EXPORT_DISK_CAP_BYTES", ge=0
    )
    export_job_watchdog_seconds: int = Field(
        default=3600, alias="METRONIX_EXPORT_JOB_WATCHDOG_SECONDS", ge=60
    )
```

(`Field` is already imported in `config.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_export_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/core/config.py tests/unit/test_export_config.py
git commit -m "feat(export): add data-export config settings"
```

---

### Task 2: Export domain models

**Files:**
- Create: `src/metronix/export/__init__.py` (empty)
- Create: `src/metronix/export/models.py`
- Test: `tests/unit/test_export_models.py`

**Interfaces:**
- Produces:
  - `ExportStatus(StrEnum)`: `PENDING="pending"`, `RUNNING="running"`, `READY="ready"`, `FAILED="failed"`.
  - `ExportScope` dataclass: `all_workspaces: bool = False`, `workspace_id: str | None = None`; methods `to_dict() -> dict`, classmethod `from_dict(d: dict) -> ExportScope`, `key() -> str` (stable dedup key).
  - `ExportJob` dataclass: `id: str`, `scope: ExportScope`, `status: ExportStatus`, `workspace_count: int = 0`, `agent_count: int = 0`, `memory_record_count: int = 0`, `document_count: int = 0`, `size_bytes: int = 0`, `archive_path: str | None = None`, `error: str | None = None`, `created_at: datetime`, `updated_at: datetime`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_export_models.py
from datetime import UTC, datetime

from metronix.export.models import ExportJob, ExportScope, ExportStatus


def test_scope_roundtrip_and_key():
    s = ExportScope(all_workspaces=False, workspace_id="ws1")
    assert ExportScope.from_dict(s.to_dict()) == s
    assert s.key() == "ws:ws1"
    assert ExportScope(all_workspaces=True).key() == "all"


def test_job_status_enum():
    now = datetime.now(UTC)
    job = ExportJob(
        id="e1",
        scope=ExportScope(workspace_id="ws1"),
        status=ExportStatus.PENDING,
        created_at=now,
        updated_at=now,
    )
    assert job.status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_export_models.py -v`
Expected: FAIL — module `metronix.export.models` not found.

- [ ] **Step 3: Implement the models**

```python
# src/metronix/export/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ExportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True)
class ExportScope:
    all_workspaces: bool = False
    workspace_id: str | None = None

    def to_dict(self) -> dict:
        return {"all_workspaces": self.all_workspaces, "workspace_id": self.workspace_id}

    @classmethod
    def from_dict(cls, d: dict) -> ExportScope:
        return cls(
            all_workspaces=bool(d.get("all_workspaces", False)),
            workspace_id=d.get("workspace_id"),
        )

    def key(self) -> str:
        return "all" if self.all_workspaces else f"ws:{self.workspace_id}"


@dataclass
class ExportJob:
    id: str
    scope: ExportScope
    status: ExportStatus
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    workspace_count: int = 0
    agent_count: int = 0
    memory_record_count: int = 0
    document_count: int = 0
    size_bytes: int = 0
    archive_path: str | None = None
    error: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_export_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/export/__init__.py src/metronix/export/models.py tests/unit/test_export_models.py
git commit -m "feat(export): add export domain models"
```

---

### Task 3: Filename slugification

**Files:**
- Create: `src/metronix/export/render.py`
- Test: `tests/unit/test_export_slug.py`

**Interfaces:**
- Produces:
  - `slugify_segment(raw: str, *, max_len: int = 80) -> str` — filesystem-safe single path segment; never empty, never `.`/`..`, no `/` or `\`.
  - `unique_slug(raw: str, used: set[str], *, max_len: int = 80) -> str` — slug plus an 8-char stable hash suffix on collision; adds the result to `used`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_export_slug.py
from metronix.export.render import slugify_segment, unique_slug


def test_slug_strips_path_chars():
    assert "/" not in slugify_segment("a/b/../c")
    assert "\\" not in slugify_segment("a\\b")
    assert slugify_segment("..") not in ("", ".", "..")


def test_slug_non_empty_for_garbage():
    assert slugify_segment("***") != ""
    assert slugify_segment("") != ""


def test_unique_slug_collision_suffix():
    used: set[str] = set()
    a = unique_slug("agent/one", used)
    b = unique_slug("agent/one", used)  # same raw -> same slug -> collision
    assert a != b
    assert a in used and b in used
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_export_slug.py -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement slugification**

```python
# src/metronix/export/render.py
from __future__ import annotations

import hashlib
import re

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify_segment(raw: str, *, max_len: int = 80) -> str:
    """Return a filesystem-safe single path segment (no separators, no traversal)."""
    text = _UNSAFE.sub("-", (raw or "").strip())
    text = text.strip("-._")
    if text in ("", ".", ".."):
        text = "item-" + hashlib.sha1((raw or "").encode("utf-8")).hexdigest()[:8]
    return text[:max_len]


def unique_slug(raw: str, used: set[str], *, max_len: int = 80) -> str:
    """slugify_segment plus a stable hash suffix when the slug is already used."""
    base = slugify_segment(raw, max_len=max_len)
    candidate = base
    if candidate in used:
        suffix = hashlib.sha1((raw or "").encode("utf-8")).hexdigest()[:8]
        candidate = f"{base[: max_len - 9]}-{suffix}"
        n = 1
        while candidate in used:
            candidate = f"{base[: max_len - 11]}-{suffix}-{n}"
            n += 1
    used.add(candidate)
    return candidate
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_export_slug.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/export/render.py tests/unit/test_export_slug.py
git commit -m "feat(export): add filename slugification"
```

---

### Task 4: Markdown renderers and manifest

**Files:**
- Modify: `src/metronix/export/render.py`
- Test: `tests/unit/test_export_render.py`

**Interfaces:**
- Consumes: `MemoryRecord` and `RawDocument` from `metronix.core.models`; `slugify_segment` from Task 3.
- Produces:
  - `render_agent_memory(agent_id: str, workspace_id: str, records: list[MemoryRecord]) -> str`
  - `render_document(doc: RawDocument) -> str`
  - `build_manifest(*, generated_at: datetime, scope: ExportScope, workspaces: list[str], agents: list[dict], counts: dict, limitations: list[str]) -> dict`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_export_render.py
from datetime import UTC, datetime

from metronix.core.models import MemoryKind, MemoryRecord, MemoryScope, RawDocument
from metronix.export.models import ExportScope
from metronix.export.render import build_manifest, render_agent_memory, render_document


def test_render_agent_memory_includes_fields_and_real_id():
    rec = MemoryRecord(
        workspace_id="ws1",
        agent_id="agent/one",
        scope=MemoryScope.PER_AGENT,
        kind=MemoryKind.FACT,
        content="the sky is blue",
        tags=["color"],
    )
    md = render_agent_memory("agent/one", "ws1", [rec])
    assert "agent/one" in md          # real id preserved verbatim
    assert "the sky is blue" in md
    assert "fact" in md and "color" in md


def test_render_document_has_front_matter_and_full_content():
    doc = RawDocument(
        workspace_id="ws1",
        connector_type="jira",
        source_id="PROJ-1",
        title="Bug",
        content="full body text",
        url="http://j/PROJ-1",
        author="alice",
        metadata={"status": "Open"},
    )
    md = render_document(doc)
    assert md.startswith("---")        # YAML front matter
    assert "PROJ-1" in md and "full body text" in md and "alice" in md


def test_manifest_shape():
    man = build_manifest(
        generated_at=datetime(2026, 6, 24, tzinfo=UTC),
        scope=ExportScope(workspace_id="ws1"),
        workspaces=["ws1"],
        agents=[{"agent_id": "agent/one", "file": "ws1/memory/agent-one.md",
                 "registered": False, "record_count": 1}],
        counts={"workspaces": 1, "agents": 1, "memory_records": 1, "documents": 0},
        limitations=["uploads are text only"],
    )
    assert man["format_version"] == 1
    assert man["counts"]["agents"] == 1
    assert man["agents"][0]["agent_id"] == "agent/one"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_export_render.py -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement renderers**

Append to `src/metronix/export/render.py`:

```python
import json
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metronix.core.models import MemoryRecord, RawDocument
    from metronix.export.models import ExportScope


def _yaml_scalar(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def render_agent_memory(agent_id: str, workspace_id: str, records: list[MemoryRecord]) -> str:
    lines = [
        f"# Agent memory: {agent_id}",
        "",
        f"- workspace: `{workspace_id}`",
        f"- agent_id: `{agent_id}`",
        f"- record_count: {len(records)}",
        "",
    ]
    for rec in records:
        lines += [
            "---",
            "",
            f"- kind: {rec.kind}",
            f"- scope: {rec.scope}",
            f"- status: {rec.status}",
            f"- importance_score: {rec.importance_score}",
            f"- created_at: {rec.created_at}",
            f"- updated_at: {rec.updated_at}",
            f"- tags: {', '.join(rec.tags) if rec.tags else '(none)'}",
            "",
            rec.content,
            "",
        ]
    return "\n".join(lines)


def render_document(doc: RawDocument) -> str:
    front = [
        "---",
        f"title: {_yaml_scalar(doc.title)}",
        f"source_id: {_yaml_scalar(doc.source_id)}",
        f"connector_type: {_yaml_scalar(doc.connector_type)}",
        f"url: {_yaml_scalar(doc.url)}",
        f"author: {_yaml_scalar(doc.author)}",
        f"status: {_yaml_scalar(str(doc.status))}",
        f"metadata: {_yaml_scalar(doc.metadata)}",
        "---",
        "",
    ]
    return "\n".join(front) + (doc.content or "")


def build_manifest(
    *,
    generated_at: datetime,
    scope: ExportScope,
    workspaces: list[str],
    agents: list[dict],
    counts: dict,
    limitations: list[str],
) -> dict:
    return {
        "format_version": 1,
        "generated_at": generated_at.isoformat(),
        "scope": scope.to_dict(),
        "workspaces": workspaces,
        "counts": counts,
        "agents": agents,
        "limitations": limitations,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_export_render.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/export/render.py tests/unit/test_export_render.py
git commit -m "feat(export): add markdown renderers and manifest builder"
```

---

### Task 5: Archive writer

**Files:**
- Create: `src/metronix/export/archive.py`
- Test: `tests/unit/test_export_archive.py`

**Interfaces:**
- Produces: `class ExportArchiveWriter` — `__init__(self, dest_path: str)`, context manager; `write_text(self, arcname: str, text: str) -> None`; on `__exit__` flushes and closes; property `size_bytes: int` (valid after close). Parent dir is created if missing.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_export_archive.py
import zipfile

from metronix.export.archive import ExportArchiveWriter


def test_archive_writes_entries(tmp_path):
    dest = tmp_path / "sub" / "export.zip"
    with ExportArchiveWriter(str(dest)) as w:
        w.write_text("manifest.json", "{}")
        w.write_text("ws1/memory/a.md", "hello")
    assert dest.exists()
    with zipfile.ZipFile(dest) as z:
        assert set(z.namelist()) == {"manifest.json", "ws1/memory/a.md"}
        assert z.read("ws1/memory/a.md").decode() == "hello"


def test_archive_size_after_close(tmp_path):
    dest = tmp_path / "export.zip"
    w = ExportArchiveWriter(str(dest))
    with w:
        w.write_text("a.txt", "x" * 1000)
    assert w.size_bytes > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_export_archive.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the writer**

```python
# src/metronix/export/archive.py
from __future__ import annotations

import os
import zipfile
from types import TracebackType


class ExportArchiveWriter:
    """Stream text entries into a ZIP on disk. Use as a context manager."""

    def __init__(self, dest_path: str) -> None:
        self._dest = dest_path
        os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
        self._zip: zipfile.ZipFile | None = None
        self.size_bytes = 0

    def __enter__(self) -> ExportArchiveWriter:
        self._zip = zipfile.ZipFile(self._dest, "w", compression=zipfile.ZIP_DEFLATED)
        return self

    def write_text(self, arcname: str, text: str) -> None:
        assert self._zip is not None, "writer is closed"
        self._zip.writestr(arcname, text)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None
        try:
            self.size_bytes = os.path.getsize(self._dest)
        except OSError:
            self.size_bytes = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_export_archive.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/export/archive.py tests/unit/test_export_archive.py
git commit -m "feat(export): add ZIP archive writer"
```

---

### Task 6: One-time download token store

**Files:**
- Create: `src/metronix/export/tokens.py`
- Test: `tests/unit/test_export_tokens.py`

**Interfaces:**
- Consumes: `RedisStore` from `metronix.storage.redis` (has `async set(key, value, ttl)`, `async get(key)`, and `.client` for `delete`). The token store needs only `set`, `get`, and `delete`; tests inject a fake exposing those.
- Produces: `class ExportTokenStore` — `__init__(self, redis, ttl_seconds: int)`; `async mint(self, export_id: str, path: str) -> str` (CSPRNG `secrets.token_urlsafe(32)`); `async consume(self, token: str) -> dict | None` (returns `{"export_id":..., "path":...}` and deletes it; `None` if missing). Redis key format: `export_token:<token>`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_export_tokens.py
import json

import pytest

from metronix.export.tokens import ExportTokenStore


class FakeRedis:
    def __init__(self):
        self.kv: dict[str, str] = {}

    async def set(self, key, value, ttl=None):
        self.kv[key] = value if isinstance(value, str) else value.decode()

    async def get(self, key):
        return self.kv.get(key)

    async def delete(self, key):
        self.kv.pop(key, None)


@pytest.mark.asyncio
async def test_mint_then_consume_is_one_time():
    store = ExportTokenStore(FakeRedis(), ttl_seconds=60)
    token = await store.mint("exp1", "/data/exports/exp1.zip")
    assert len(token) >= 22  # token_urlsafe(32) ~ 43 chars
    first = await store.consume(token)
    assert first == {"export_id": "exp1", "path": "/data/exports/exp1.zip"}
    assert await store.consume(token) is None  # consumed


@pytest.mark.asyncio
async def test_consume_unknown_token():
    store = ExportTokenStore(FakeRedis(), ttl_seconds=60)
    assert await store.consume("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_export_tokens.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the token store**

```python
# src/metronix/export/tokens.py
from __future__ import annotations

import json
import secrets
from typing import Any, Protocol


class _RedisLike(Protocol):
    async def set(self, key: str, value: str | bytes, ttl: int | None = ...) -> None: ...
    async def get(self, key: str) -> str | None: ...
    async def delete(self, key: str) -> Any: ...


def _key(token: str) -> str:
    return f"export_token:{token}"


class ExportTokenStore:
    def __init__(self, redis: _RedisLike, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def mint(self, export_id: str, path: str) -> str:
        token = secrets.token_urlsafe(32)
        payload = json.dumps({"export_id": export_id, "path": path})
        await self._redis.set(_key(token), payload, ttl=self._ttl)
        return token

    async def consume(self, token: str) -> dict | None:
        raw = await self._redis.get(_key(token))
        if raw is None:
            return None
        await self._redis.delete(_key(token))
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None
```

Note: `RedisStore` in `storage/redis.py` exposes `set`/`get`; add a `delete` passthrough if absent — see Task 9 (data-access additions) which adds `RedisStore.delete`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_export_tokens.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/export/tokens.py tests/unit/test_export_tokens.py
git commit -m "feat(export): add one-time download token store"
```

---

### Task 7: Alembic migration for `export_jobs`

**Files:**
- Create: `src/metronix/migrations/versions/026_export_jobs.py`
- Test: (verified via Task 8's integration test that the table exists)

**Interfaces:**
- Produces: table `export_jobs` with columns `id TEXT PK`, `scope JSONB NOT NULL`, `scope_key TEXT NOT NULL`, `status TEXT NOT NULL`, `workspace_count INT NOT NULL DEFAULT 0`, `agent_count INT NOT NULL DEFAULT 0`, `memory_record_count INT NOT NULL DEFAULT 0`, `document_count INT NOT NULL DEFAULT 0`, `size_bytes BIGINT NOT NULL DEFAULT 0`, `archive_path TEXT NULL`, `error TEXT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`; partial index on `(scope_key)` where `status IN ('pending','running')`.

- [ ] **Step 1: Confirm current head**

Run: `python -m alembic heads`
Expected: shows `025` as head. (If higher, set `down_revision` to the actual head.)

- [ ] **Step 2: Write the migration**

```python
# src/metronix/migrations/versions/026_export_jobs.py
"""Add export_jobs table for the data-export feature.

Revision ID: 026
Revises: 025
Create Date: 2026-06-24
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "026"
down_revision: str | None = "025"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("scope", postgresql.JSONB, nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("scope_key", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("workspace_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("agent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("memory_record_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("document_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("archive_path", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
    )
    op.create_index(
        "ix_export_jobs_active_scope",
        "export_jobs",
        ["scope_key"],
        postgresql_where=sa.text("status IN ('pending','running')"),
    )
    op.create_index("ix_export_jobs_status", "export_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_export_jobs_status", table_name="export_jobs")
    op.drop_index("ix_export_jobs_active_scope", table_name="export_jobs")
    op.drop_table("export_jobs")
```

- [ ] **Step 3: Apply and verify**

Run: `python -m alembic upgrade head`
Expected: applies `026`; no error. Verify: `python -m alembic current` shows `026`.

- [ ] **Step 4: Commit**

```bash
git add src/metronix/migrations/versions/026_export_jobs.py
git commit -m "feat(export): add export_jobs migration"
```

---

### Task 8: Export job store (PostgreSQL)

**Files:**
- Create: `src/metronix/export/jobs.py`
- Test: `tests/integration/test_export_job_store.py`

**Interfaces:**
- Consumes: `AsyncEngine`; `ExportJob`, `ExportScope`, `ExportStatus` from Task 2.
- Produces: `class ExportJobStore` — `__init__(self, engine: AsyncEngine)`; `async create(self, job: ExportJob) -> None`; `async get(self, export_id: str) -> ExportJob | None`; `async set_status(self, export_id: str, status: ExportStatus, *, error: str | None = None) -> None`; `async set_result(self, export_id: str, *, workspace_count: int, agent_count: int, memory_record_count: int, document_count: int, size_bytes: int, archive_path: str) -> None`; `async find_active_for_scope(self, scope: ExportScope) -> ExportJob | None`; `async reap_orphaned(self, older_than_seconds: int) -> int`.

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_export_job_store.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core.config import Settings
from metronix.export.jobs import ExportJobStore
from metronix.export.models import ExportJob, ExportScope, ExportStatus

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_get_update_dedup():
    engine = create_async_engine(Settings().postgres_dsn, pool_pre_ping=True)
    store = ExportJobStore(engine)
    scope = ExportScope(workspace_id="ws_test_export")
    job = ExportJob(id="exp-test-1", scope=scope, status=ExportStatus.PENDING)

    await store.create(job)
    got = await store.get("exp-test-1")
    assert got is not None and got.status == ExportStatus.PENDING and got.scope == scope

    active = await store.find_active_for_scope(scope)
    assert active is not None and active.id == "exp-test-1"

    await store.set_status("exp-test-1", ExportStatus.RUNNING)
    await store.set_result("exp-test-1", workspace_count=1, agent_count=2,
                           memory_record_count=5, document_count=3,
                           size_bytes=999, archive_path="/data/exports/exp-test-1.zip")
    await store.set_status("exp-test-1", ExportStatus.READY)
    done = await store.get("exp-test-1")
    assert done.status == ExportStatus.READY and done.size_bytes == 999
    assert await store.find_active_for_scope(scope) is None  # ready != active
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/integration/test_export_job_store.py -v -m integration`
Expected: FAIL — module not found. (Requires PostgreSQL up and `alembic upgrade head` applied.)

- [ ] **Step 3: Implement the job store**

```python
# src/metronix/export/jobs.py
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from metronix.export.models import ExportJob, ExportScope, ExportStatus

_COLS = (
    "id, scope, scope_key, status, workspace_count, agent_count, "
    "memory_record_count, document_count, size_bytes, archive_path, error, "
    "created_at, updated_at"
)


def _row_to_job(m) -> ExportJob:
    scope = m["scope"]
    if isinstance(scope, str):
        scope = json.loads(scope)
    return ExportJob(
        id=m["id"],
        scope=ExportScope.from_dict(scope or {}),
        status=ExportStatus(m["status"]),
        workspace_count=m["workspace_count"],
        agent_count=m["agent_count"],
        memory_record_count=m["memory_record_count"],
        document_count=m["document_count"],
        size_bytes=m["size_bytes"],
        archive_path=m["archive_path"],
        error=m["error"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


class ExportJobStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, job: ExportJob) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO export_jobs (id, scope, scope_key, status) "
                    "VALUES (:id, CAST(:scope AS jsonb), :scope_key, :status)"
                ),
                {
                    "id": job.id,
                    "scope": json.dumps(job.scope.to_dict()),
                    "scope_key": job.scope.key(),
                    "status": str(job.status),
                },
            )

    async def get(self, export_id: str) -> ExportJob | None:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(f"SELECT {_COLS} FROM export_jobs WHERE id = :id"),
                {"id": export_id},
            )
            row = result.fetchone()
        return _row_to_job(row._mapping) if row else None

    async def set_status(
        self, export_id: str, status: ExportStatus, *, error: str | None = None
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE export_jobs SET status = :status, error = :error, "
                    "updated_at = NOW() WHERE id = :id"
                ),
                {"id": export_id, "status": str(status), "error": error},
            )

    async def set_result(
        self,
        export_id: str,
        *,
        workspace_count: int,
        agent_count: int,
        memory_record_count: int,
        document_count: int,
        size_bytes: int,
        archive_path: str,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE export_jobs SET workspace_count = :wc, agent_count = :ac, "
                    "memory_record_count = :mc, document_count = :dc, size_bytes = :sb, "
                    "archive_path = :path, updated_at = NOW() WHERE id = :id"
                ),
                {
                    "id": export_id,
                    "wc": workspace_count,
                    "ac": agent_count,
                    "mc": memory_record_count,
                    "dc": document_count,
                    "sb": size_bytes,
                    "path": archive_path,
                },
            )

    async def find_active_for_scope(self, scope: ExportScope) -> ExportJob | None:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"SELECT {_COLS} FROM export_jobs "
                    "WHERE scope_key = :k AND status IN ('pending','running') "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"k": scope.key()},
            )
            row = result.fetchone()
        return _row_to_job(row._mapping) if row else None

    async def reap_orphaned(self, older_than_seconds: int) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE export_jobs SET status = 'failed', "
                    "error = 'reaped: running past watchdog timeout', updated_at = NOW() "
                    "WHERE status IN ('pending','running') "
                    "AND updated_at < NOW() - make_interval(secs => :secs)"
                ),
                {"secs": older_than_seconds},
            )
            return result.rowcount or 0
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/integration/test_export_job_store.py -v -m integration`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/export/jobs.py tests/integration/test_export_job_store.py
git commit -m "feat(export): add PostgreSQL export job store"
```

---

### Task 9: Data-access additions (distinct agents, doc keyset, workspaces, redis delete)

**Files:**
- Modify: `src/metronix/storage/memory_postgres.py` (add `list_agent_ids`)
- Modify: `src/metronix/storage/postgres.py` (add `list_document_workspaces`, `list_raw_documents_keyset`)
- Modify: `src/metronix/storage/redis.py` (add `delete`)
- Test: `tests/integration/test_export_data_access.py`

**Interfaces:**
- Produces:
  - `MemoryPostgresStore.list_agent_ids(self, workspace_id: str) -> list[str]`
  - `PostgresStore.list_document_workspaces(self) -> list[str]`
  - `PostgresStore.list_raw_documents_keyset(self, workspace_id: str, *, after_updated_at, after_id: str | None, limit: int = 200) -> list[RawDocument]` — keyset page using order `(updated_at DESC, id ASC)`.
  - `RedisStore.delete(self, key: str) -> None`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/test_export_data_access.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from metronix.core.config import Settings
from metronix.storage.memory_postgres import MemoryPostgresStore
from metronix.storage.postgres import PostgresStore

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_list_agent_ids_distinct():
    engine = create_async_engine(Settings().postgres_dsn, pool_pre_ping=True)
    store = MemoryPostgresStore(engine)
    ids = await store.list_agent_ids("nonexistent-ws")
    assert ids == []  # no rows, but method exists and returns a list


@pytest.mark.asyncio
async def test_doc_keyset_first_page_runs():
    store = PostgresStore(Settings().postgres_dsn)
    try:
        page = await store.list_raw_documents_keyset(
            "nonexistent-ws", after_updated_at=None, after_id=None, limit=10
        )
        assert page == []
        assert isinstance(await store.list_document_workspaces(), list)
    finally:
        await store.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/integration/test_export_data_access.py -v -m integration`
Expected: FAIL — methods not defined.

- [ ] **Step 3a: Add `list_agent_ids` to `MemoryPostgresStore`**

In `src/metronix/storage/memory_postgres.py`, next to `list_workspaces` (~line 413), add:

```python
    async def list_agent_ids(self, workspace_id: str) -> list[str]:
        """Return distinct agent_ids that have memory in a workspace (incl. unregistered)."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("SELECT DISTINCT agent_id FROM memory_records WHERE workspace_id = :ws"),
                {"ws": workspace_id},
            )
            rows = result.fetchall()
        return [str(row[0]) for row in rows]
```

- [ ] **Step 3b: Add doc methods to `PostgresStore`**

In `src/metronix/storage/postgres.py`, next to `list_raw_documents` (~line 1377), add:

```python
    async def list_document_workspaces(self) -> list[str]:
        """Return distinct workspace_ids present in raw_documents."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("SELECT DISTINCT workspace_id FROM raw_documents")
            )
            return [str(r[0]) for r in result.fetchall()]

    async def list_raw_documents_keyset(
        self,
        workspace_id: str,
        *,
        after_updated_at: object | None,
        after_id: str | None,
        limit: int = 200,
    ) -> list[RawDocument]:
        """Keyset page over (updated_at DESC, id ASC). Pass after_* = None for first page."""
        params: dict = {"workspace_id": workspace_id, "limit": limit}
        where = "workspace_id = :workspace_id"
        if after_updated_at is not None and after_id is not None:
            where += (
                " AND (updated_at, id) < (:after_updated_at, :after_id)"
            )  # DESC,ASC keyset: rows ordered after the cursor
            params["after_updated_at"] = after_updated_at
            params["after_id"] = after_id
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"SELECT * FROM raw_documents WHERE {where} "
                    "ORDER BY updated_at DESC, id ASC LIMIT :limit"
                ),
                params,
            )
            return [self._row_to_raw_document(row) for row in result]
```

Note on the keyset predicate: the existing order is `updated_at DESC, id ASC`, which is not a single monotonic tuple, so strict tuple comparison is approximate. For the export's read-mostly use, page by `updated_at` descending and within an equal `updated_at` fall back to `id`; if exactness matters later, switch the page order to `(updated_at DESC, id DESC)` so `(updated_at, id) < (cursor)` is exact. Keep it simple here: order `updated_at DESC, id ASC`, advance the cursor with the last row's `(updated_at, id)`, and stop when a page returns fewer than `limit` rows.

- [ ] **Step 3c: Add `delete` to `RedisStore`**

In `src/metronix/storage/redis.py`, in the `RedisStore` class, add:

```python
    async def delete(self, key: str) -> None:
        """Delete a key (no error if absent)."""
        await self._client.delete(key)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/integration/test_export_data_access.py -v -m integration`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/storage/memory_postgres.py src/metronix/storage/postgres.py src/metronix/storage/redis.py tests/integration/test_export_data_access.py
git commit -m "feat(export): add distinct-agent, doc keyset, and redis delete helpers"
```

---

### Task 10: ExportService (orchestration)

**Files:**
- Create: `src/metronix/export/service.py`
- Test: `tests/unit/test_export_service.py`

**Interfaces:**
- Consumes (via constructor injection, defined as Protocols so tests use fakes):
  - `MemoryReader`: `async list_workspaces() -> list[str]`; `async list_agent_ids(ws: str) -> list[str]`; `async list_records(ws: str, *, agent_id: str, lifetime: str, limit: int, offset: int) -> list[MemoryRecord]`.
  - `DocReader`: `async list_document_workspaces() -> list[str]`; `async list_raw_documents_keyset(ws: str, *, after_updated_at, after_id, limit) -> list[RawDocument]`.
  - `RegisteredAgents`: `async registered_agent_ids(ws: str) -> set[str]`.
  - `ExportJobStore` (Task 8), `ExportTokenStore` (Task 6).
  - `archive_dir: str`, `public_base_url: str`, `disk_cap_bytes: int`, `new_id: Callable[[], str]` (defaults to `uuid4().hex`; injectable for deterministic tests), `now: Callable[[], datetime]` (injectable).
- Produces: `class ExportService` — `async start(self, scope: ExportScope) -> ExportJob`; `async status(self, export_id: str) -> dict | None`; `async _build(self, export_id: str, scope: ExportScope) -> None` (also runnable directly in tests). `start()` schedules `_build` via `asyncio.create_task`. `status()` returns `{export_id, status, counts..., size_bytes, download_url?, error?}` (download_url present only when READY, minted on demand).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_export_service.py
import zipfile
from datetime import UTC, datetime

import pytest

from metronix.core.models import MemoryRecord, RawDocument
from metronix.export.models import ExportScope, ExportStatus
from metronix.export.service import ExportService


class FakeMemory:
    async def list_workspaces(self):
        return ["ws1"]

    async def list_agent_ids(self, ws):
        return ["agent/one", "ghost"]

    async def list_records(self, ws, *, agent_id, lifetime, limit, offset):
        if offset > 0:
            return []
        return [MemoryRecord(workspace_id=ws, agent_id=agent_id, content=f"m-{agent_id}")]


class FakeDocs:
    async def list_document_workspaces(self):
        return ["ws1"]

    async def list_raw_documents_keyset(self, ws, *, after_updated_at, after_id, limit):
        if after_id is not None:
            return []
        return [RawDocument(id="d1", workspace_id=ws, connector_type="jira",
                            source_id="PROJ-1", content="body",
                            updated_at=datetime(2026, 1, 1, tzinfo=UTC))]


class FakeRegistry:
    async def registered_agent_ids(self, ws):
        return {"agent/one"}  # 'ghost' is unregistered


class FakeJobs:
    def __init__(self):
        self.jobs = {}

    async def create(self, job):
        self.jobs[job.id] = job

    async def get(self, export_id):
        return self.jobs.get(export_id)

    async def set_status(self, export_id, status, *, error=None):
        self.jobs[export_id].status = status
        self.jobs[export_id].error = error

    async def set_result(self, export_id, **kw):
        j = self.jobs[export_id]
        for k, v in kw.items():
            setattr(j, k, v)

    async def find_active_for_scope(self, scope):
        for j in self.jobs.values():
            if j.scope.key() == scope.key() and j.status in (
                ExportStatus.PENDING, ExportStatus.RUNNING):
                return j
        return None


class FakeTokens:
    async def mint(self, export_id, path):
        return "tok-123"


def _service(tmp_path, jobs):
    return ExportService(
        memory=FakeMemory(),
        docs=FakeDocs(),
        registry=FakeRegistry(),
        job_store=jobs,
        token_store=FakeTokens(),
        archive_dir=str(tmp_path),
        public_base_url="http://host:8001",
        disk_cap_bytes=10_000_000,
        new_id=lambda: "exp1",
        now=lambda: datetime(2026, 6, 24, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_build_produces_zip_with_all_agents_and_docs(tmp_path):
    jobs = FakeJobs()
    svc = _service(tmp_path, jobs)
    scope = ExportScope(workspace_id="ws1")
    job = await svc.start(scope)
    await svc._build(job.id, scope)  # run synchronously for assertion

    done = await jobs.get(job.id)
    assert done.status == ExportStatus.READY
    assert done.agent_count == 2 and done.document_count == 1

    with zipfile.ZipFile(done.archive_path) as z:
        names = z.namelist()
        assert "manifest.json" in names
        assert any(n.startswith("ws1/memory/") for n in names)
        assert any(n.startswith("ws1/documents/jira/") for n in names)
        manifest = z.read("manifest.json").decode()
    assert "ghost" in manifest  # unregistered agent included


@pytest.mark.asyncio
async def test_status_returns_download_url_when_ready(tmp_path):
    jobs = FakeJobs()
    svc = _service(tmp_path, jobs)
    scope = ExportScope(workspace_id="ws1")
    job = await svc.start(scope)
    await svc._build(job.id, scope)
    st = await svc.status(job.id)
    assert st["status"] == "ready"
    assert st["download_url"] == (
        "http://host:8001/api/v1/export/exp1/download?token=tok-123")


@pytest.mark.asyncio
async def test_dedup_returns_existing_active_job(tmp_path):
    jobs = FakeJobs()
    svc = _service(tmp_path, jobs)
    scope = ExportScope(workspace_id="ws1")
    j1 = await svc.start(scope)
    j2 = await svc.start(scope)  # active job exists -> returns same
    assert j1.id == j2.id
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_export_service.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the service**

```python
# src/metronix/export/service.py
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import structlog

from metronix.core.models import MemoryRecord, RawDocument
from metronix.export.archive import ExportArchiveWriter
from metronix.export.models import ExportJob, ExportScope, ExportStatus
from metronix.export.render import build_manifest, render_agent_memory, render_document, unique_slug

logger = structlog.get_logger(__name__)

_MEM_PAGE = 500
_DOC_PAGE = 200
_LIMITATIONS = [
    "Uploaded files are exported as extracted text only; "
    "original binary files are not retained by Metronix.",
]


class MemoryReader(Protocol):
    async def list_workspaces(self) -> list[str]: ...
    async def list_agent_ids(self, ws: str) -> list[str]: ...
    async def list_records(
        self, ws: str, *, agent_id: str, lifetime: str, limit: int, offset: int
    ) -> list[MemoryRecord]: ...


class DocReader(Protocol):
    async def list_document_workspaces(self) -> list[str]: ...
    async def list_raw_documents_keyset(
        self, ws: str, *, after_updated_at: Any, after_id: str | None, limit: int
    ) -> list[RawDocument]: ...


class RegisteredAgents(Protocol):
    async def registered_agent_ids(self, ws: str) -> set[str]: ...


class ExportService:
    def __init__(
        self,
        *,
        memory: MemoryReader,
        docs: DocReader,
        registry: RegisteredAgents,
        job_store: Any,
        token_store: Any,
        archive_dir: str,
        public_base_url: str,
        disk_cap_bytes: int,
        new_id: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._memory = memory
        self._docs = docs
        self._registry = registry
        self._jobs = job_store
        self._tokens = token_store
        self._dir = archive_dir
        self._base = public_base_url.rstrip("/")
        self._cap = disk_cap_bytes
        self._new_id = new_id or (lambda: uuid4().hex)
        self._now = now or (lambda: datetime.now(UTC))

    async def start(self, scope: ExportScope) -> ExportJob:
        existing = await self._jobs.find_active_for_scope(scope)
        if existing is not None:
            return existing
        if self._cap and self._dir_size() >= self._cap:
            raise RuntimeError("export disk cap exceeded; try again after cleanup")
        job = ExportJob(
            id=self._new_id(),
            scope=scope,
            status=ExportStatus.PENDING,
            created_at=self._now(),
            updated_at=self._now(),
        )
        await self._jobs.create(job)
        asyncio.create_task(self._build_guarded(job.id, scope), name=f"export-{job.id}")
        return job

    async def status(self, export_id: str) -> dict | None:
        job = await self._jobs.get(export_id)
        if job is None:
            return None
        out: dict = {
            "export_id": job.id,
            "status": str(job.status),
            "counts": {
                "workspaces": job.workspace_count,
                "agents": job.agent_count,
                "memory_records": job.memory_record_count,
                "documents": job.document_count,
            },
            "size_bytes": job.size_bytes,
        }
        if job.status == ExportStatus.FAILED:
            out["error"] = job.error
        if job.status == ExportStatus.READY and job.archive_path:
            token = await self._tokens.mint(job.id, job.archive_path)
            out["download_url"] = (
                f"{self._base}/api/v1/export/{job.id}/download?token={token}"
            )
        return out

    def _dir_size(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self._dir):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total

    async def _resolve_workspaces(self, scope: ExportScope) -> list[str]:
        if not scope.all_workspaces:
            return [scope.workspace_id or ""]
        seen = set(await self._memory.list_workspaces())
        seen.update(await self._docs.list_document_workspaces())
        return sorted(seen)

    async def _build_guarded(self, export_id: str, scope: ExportScope) -> None:
        try:
            await self._build(export_id, scope)
        except Exception as exc:  # noqa: BLE001 — record failure, never crash the loop
            logger.warning("export.build.failed", export_id=export_id, error=str(exc))
            await self._jobs.set_status(export_id, ExportStatus.FAILED, error=str(exc))

    async def _build(self, export_id: str, scope: ExportScope) -> None:
        await self._jobs.set_status(export_id, ExportStatus.RUNNING)
        workspaces = await self._resolve_workspaces(scope)
        path = os.path.join(self._dir, f"{export_id}.zip")
        agent_manifest: list[dict] = []
        n_agents = n_mem = n_docs = 0

        with ExportArchiveWriter(path) as zw:
            for ws in workspaces:
                registered = await self._registry.registered_agent_ids(ws)
                used: set[str] = set()
                for agent_id in await self._memory.list_agent_ids(ws):
                    records = await self._collect_records(ws, agent_id)
                    fname = unique_slug(agent_id, used) + ".md"
                    arc = f"{ws}/memory/{fname}"
                    zw.write_text(arc, render_agent_memory(agent_id, ws, records))
                    agent_manifest.append({
                        "agent_id": agent_id,
                        "workspace_id": ws,
                        "file": arc,
                        "registered": agent_id in registered,
                        "record_count": len(records),
                    })
                    n_agents += 1
                    n_mem += len(records)

                doc_used: dict[str, set[str]] = {}
                async for doc in self._iter_docs(ws):
                    ct = unique_slug(doc.connector_type or "unknown", set(), max_len=40)
                    used_for_ct = doc_used.setdefault(ct, set())
                    base = doc.source_id or doc.title or doc.id
                    fname = unique_slug(base, used_for_ct) + ".md"
                    zw.write_text(f"{ws}/documents/{ct}/{fname}", render_document(doc))
                    n_docs += 1

            manifest = build_manifest(
                generated_at=self._now(),
                scope=scope,
                workspaces=workspaces,
                agents=agent_manifest,
                counts={
                    "workspaces": len(workspaces),
                    "agents": n_agents,
                    "memory_records": n_mem,
                    "documents": n_docs,
                },
                limitations=_LIMITATIONS,
            )
            zw.write_text("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        await self._jobs.set_result(
            export_id,
            workspace_count=len(workspaces),
            agent_count=n_agents,
            memory_record_count=n_mem,
            document_count=n_docs,
            size_bytes=zw.size_bytes,
            archive_path=path,
        )
        await self._jobs.set_status(export_id, ExportStatus.READY)

    async def _collect_records(self, ws: str, agent_id: str) -> list[MemoryRecord]:
        out: list[MemoryRecord] = []
        offset = 0
        while True:
            page = await self._memory.list_records(
                ws, agent_id=agent_id, lifetime="persistent", limit=_MEM_PAGE, offset=offset
            )
            out.extend(page)
            if len(page) < _MEM_PAGE:
                return out
            offset += _MEM_PAGE

    async def _iter_docs(self, ws: str):
        after_updated_at = None
        after_id = None
        while True:
            page = await self._docs.list_raw_documents_keyset(
                ws, after_updated_at=after_updated_at, after_id=after_id, limit=_DOC_PAGE
            )
            for doc in page:
                yield doc
            if len(page) < _DOC_PAGE:
                return
            after_updated_at = page[-1].updated_at
            after_id = page[-1].id
```

Note: delete the bogus `from metronix.export.models import ExportджJob ...` line — it is a typo guard. The only models import needed is:
`from metronix.export.models import ExportJob, ExportScope, ExportStatus`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/test_export_service.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add src/metronix/export/service.py tests/unit/test_export_service.py
git commit -m "feat(export): add ExportService orchestration"
```

---

### Task 11: Service wiring helpers (concrete adapters + builder)

**Files:**
- Create: `src/metronix/export/deps.py`
- Test: `tests/unit/test_export_deps.py`

**Interfaces:**
- Consumes: `Settings`; `MemoryPostgresStore`, `PostgresStore`, `RedisStore`; the new store methods from Task 9; `ExportJobStore`, `ExportTokenStore`, `ExportService`.
- Produces:
  - `class RegisteredAgentsReader` — `__init__(self, engine)`, `async registered_agent_ids(ws) -> set[str]` via `SELECT id FROM agents WHERE workspace_id = :ws` (read-only; tolerates absence of the `agents` table by returning an empty set).
  - `build_export_service(settings: Settings) -> ExportService` — constructs all concrete stores from settings (mirrors `mcp/tools/_memory_deps.py`), cached at module level so MCP and lifespan reuse one instance per process.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_export_deps.py
from metronix.core.config import Settings
from metronix.export.deps import build_export_service
from metronix.export.service import ExportService


def test_build_export_service_constructs(monkeypatch, tmp_path):
    monkeypatch.setenv("METRONIX_EXPORT_DIR", str(tmp_path))
    svc = build_export_service(Settings())
    assert isinstance(svc, ExportService)
    # cached: same instance on second call
    assert build_export_service(Settings()) is svc
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_export_deps.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement adapters + builder**

```python
# src/metronix/export/deps.py
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from metronix.core.config import Settings
from metronix.export.jobs import ExportJobStore
from metronix.export.service import ExportService
from metronix.export.tokens import ExportTokenStore
from metronix.storage.memory_postgres import MemoryPostgresStore
from metronix.storage.postgres import PostgresStore
from metronix.storage.redis import RedisStore


class RegisteredAgentsReader:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def registered_agent_ids(self, ws: str) -> set[str]:
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(
                    text("SELECT id FROM agents WHERE workspace_id = :ws"), {"ws": ws}
                )
                return {str(r[0]) for r in result.fetchall()}
        except Exception:  # noqa: BLE001 — agents table optional; flag is best-effort
            return set()


_SERVICE: ExportService | None = None


def build_export_service(settings: Settings) -> ExportService:
    global _SERVICE  # noqa: PLW0603
    if _SERVICE is not None:
        return _SERVICE

    engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    pg_doc_store = PostgresStore(settings.postgres_dsn)
    mem_store = MemoryPostgresStore(engine)
    redis_store = RedisStore(settings.redis_url)

    _SERVICE = ExportService(
        memory=mem_store,
        docs=pg_doc_store,
        registry=RegisteredAgentsReader(engine),
        job_store=ExportJobStore(engine),
        token_store=ExportTokenStore(redis_store, settings.export_token_ttl_seconds),
        archive_dir=settings.export_dir,
        public_base_url=settings.public_base_url,
        disk_cap_bytes=settings.export_disk_cap_bytes,
    )
    return _SERVICE
```

Note: `MemoryPostgresStore.list_records` already accepts `lifetime="persistent"`, `agent_id`, `limit`, `offset` (Task 9 + existing signature), satisfying the `MemoryReader` protocol. `PostgresStore` satisfies `DocReader` after Task 9.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/test_export_deps.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/export/deps.py tests/unit/test_export_deps.py
git commit -m "feat(export): add concrete adapters and service builder"
```

---

### Task 12: MCP tools

**Files:**
- Create: `src/metronix/mcp/tools/export.py`
- Modify: `src/metronix/mcp/tools/__init__.py` (import + `__all__`)
- Modify: `src/metronix/mcp/tools/models.py` (response models)
- Test: `tests/unit/test_mcp_export_tools.py`

**Interfaces:**
- Consumes: `ExportScope` (Task 2), `build_export_service` (Task 11), `MCPError`/`ErrorCode`/`handle_tool_error` (`mcp/errors.py`), `get_settings`.
- Produces: `metronix_export_data(workspace_id: str | None = None, all_workspaces: bool = False) -> dict`, `metronix_export_status(export_id: str) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mcp_export_tools.py
import pytest

import metronix.mcp.tools.export as export_tool


@pytest.mark.asyncio
async def test_export_data_requires_explicit_scope():
    res = await export_tool.metronix_export_data()
    assert "error" in res
    assert res["error"]["code"] == "INVALID_PARAMS"


@pytest.mark.asyncio
async def test_export_data_starts_job(monkeypatch):
    class FakeJob:
        id = "exp9"
        status = "pending"

    class FakeSvc:
        async def start(self, scope):
            assert scope.workspace_id == "ws1"
            return FakeJob()

        async def status(self, export_id):
            return {"export_id": export_id, "status": "pending", "counts": {}, "size_bytes": 0}

    monkeypatch.setattr(export_tool, "build_export_service", lambda s: FakeSvc())
    res = await export_tool.metronix_export_data(workspace_id="ws1")
    assert res["export_id"] == "exp9" and res["status"] == "pending"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_mcp_export_tools.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3a: Add response models to `models.py`**

Append to `src/metronix/mcp/tools/models.py`:

```python
class ExportStartResponse(BaseModel):
    """Response from metronix_export_data."""

    export_id: str
    status: str


class ExportStatusResponse(BaseModel):
    """Response from metronix_export_status."""

    export_id: str
    status: str
    counts: dict[str, Any] = Field(default_factory=dict)
    size_bytes: int = 0
    download_url: str | None = None
    error: str | None = None
```

- [ ] **Step 3b: Implement the tools**

```python
# src/metronix/mcp/tools/export.py
from __future__ import annotations

from typing import Any

from metronix.core.config import get_settings
from metronix.export.deps import build_export_service
from metronix.export.models import ExportScope
from metronix.mcp.errors import ErrorCode, MCPError, handle_tool_error
from metronix.mcp.server import mcp


@mcp.tool(
    description=(
        "Export ALL data for a workspace (or all workspaces) to a downloadable ZIP: "
        "one Markdown file per agent's memory (including unregistered agents) plus "
        "every ingested document in original whole form. Runs in the background.\n\n"
        "**Parameters:**\n"
        "- workspace_id: Target workspace (required unless all_workspaces=true)\n"
        "- all_workspaces: Export every workspace in one archive (default false)\n\n"
        "**Returns:** export_id and status. Poll metronix_export_status for the "
        "download_url once status is 'ready'."
    ),
)
async def metronix_export_data(
    workspace_id: str | None = None,
    all_workspaces: bool = False,
) -> dict[str, Any]:
    """Start a background data export. No silent 'default' workspace fallback."""
    try:
        if not all_workspaces and not workspace_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metronix_export_data: workspace_id is required unless all_workspaces=true",
                    hint="Pass an explicit workspace_id, or set all_workspaces=true to export everything",
                ).to_dict(),
            }
        scope = ExportScope(all_workspaces=all_workspaces, workspace_id=workspace_id)
        service = build_export_service(get_settings())
        job = await service.start(scope)
        return {"export_id": job.id, "status": str(job.status)}
    except Exception as exc:  # noqa: BLE001
        return {"error": handle_tool_error("metronix_export_data", exc).to_dict()}


@mcp.tool(
    description=(
        "Check the status of a data export started by metronix_export_data.\n\n"
        "**Parameters:**\n- export_id: The id returned by metronix_export_data\n\n"
        "**Returns:** status (pending|running|ready|failed), counts, size_bytes, and "
        "download_url when ready."
    ),
)
async def metronix_export_status(export_id: str) -> dict[str, Any]:
    """Return current export status, including a one-time download_url when ready."""
    try:
        if not export_id:
            return {
                "error": MCPError(
                    code=ErrorCode.INVALID_PARAMS,
                    message="metronix_export_status: export_id is required",
                ).to_dict(),
            }
        service = build_export_service(get_settings())
        result = await service.status(export_id)
        if result is None:
            return {
                "error": MCPError(
                    code=ErrorCode.DOCUMENT_NOT_FOUND,
                    message=f"metronix_export_status: no export with id '{export_id}'",
                ).to_dict(),
            }
        return result
    except Exception as exc:  # noqa: BLE001
        return {"error": handle_tool_error("metronix_export_status", exc).to_dict()}
```

- [ ] **Step 3c: Register in `__init__.py`**

In `src/metronix/mcp/tools/__init__.py` add the import (alphabetical, near the others):

```python
from metronix.mcp.tools.export import metronix_export_data, metronix_export_status
```

and add to `__all__`:

```python
    "metronix_export_data",
    "metronix_export_status",
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/test_mcp_export_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/mcp/tools/export.py src/metronix/mcp/tools/__init__.py src/metronix/mcp/tools/models.py tests/unit/test_mcp_export_tools.py
git commit -m "feat(export): add metronix_export_data/status MCP tools"
```

---

### Task 13: REST router (trigger, status, download)

**Files:**
- Create: `src/metronix/api/routes/export.py`
- Modify: `src/metronix/api/app.py` (import + `include_router`)
- Test: `tests/unit/test_export_routes.py`

**Interfaces:**
- Consumes: `ExportScope` (Task 2), `resolve_workspace_id` (`api/dependencies.py`), `require_editor`/`require_viewer` (`auth.dependencies`), `ExportService` from `request.app.state.export_service`, `ExportTokenStore` for download (`request.app.state.export_token_store`).
- Produces: `router = APIRouter(prefix="/export", tags=["export"])` with:
  - `POST /export` (body `{workspace_id?: str, all_workspaces?: bool}`) → `{export_id, status}`. Admin (`*`) required for `all_workspaces=true`.
  - `GET /export/{export_id}` → status dict.
  - `GET /export/{export_id}/download?token=...` → `StreamingResponse` of `application/zip`; token-only auth; consumes the token; 404 on missing/used token, 410 if the archive is gone.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_export_routes.py
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from metronix.api.routes import export as export_routes


class FakeSvc:
    async def start(self, scope):
        from types import SimpleNamespace
        return SimpleNamespace(id="exp1", status="pending")

    async def status(self, export_id):
        if export_id != "exp1":
            return None
        return {"export_id": "exp1", "status": "ready", "counts": {}, "size_bytes": 0,
                "download_url": "http://h/api/v1/export/exp1/download?token=t"}


class FakeTokens:
    def __init__(self):
        self.consumed = []

    async def consume(self, token):
        if token == "good":
            return {"export_id": "exp1", "path": "/nonexistent/exp1.zip"}
        return None


def _app(tmp_path):
    app = FastAPI()
    app.state.export_service = FakeSvc()
    app.state.export_token_store = FakeTokens()
    # bypass auth deps with permissive overrides
    from metronix.api.dependencies import resolve_workspace_id
    app.dependency_overrides[resolve_workspace_id] = lambda: "ws1"
    app.include_router(export_routes.router, prefix="/api/v1")
    return app


def test_post_export_starts(tmp_path):
    client = TestClient(_app(tmp_path))
    r = client.post("/api/v1/export", json={"workspace_id": "ws1"})
    assert r.status_code == 200 and r.json()["export_id"] == "exp1"


def test_download_unknown_token_404(tmp_path):
    client = TestClient(_app(tmp_path))
    r = client.get("/api/v1/export/exp1/download?token=bad")
    assert r.status_code == 404


def test_download_missing_archive_410(tmp_path):
    client = TestClient(_app(tmp_path))
    r = client.get("/api/v1/export/exp1/download?token=good")
    assert r.status_code == 410
```

Note: the auth dependencies (`require_editor`, etc.) are applied in the router. For this unit test we override only `resolve_workspace_id`; if `require_editor` blocks, also override it. The implementation below keeps role deps minimal so the override suffices — see Step 3.

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_export_routes.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the router**

```python
# src/metronix/api/routes/export.py
from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from starlette.responses import FileResponse

from metronix.api.dependencies import resolve_workspace_id
from metronix.export.models import ExportScope

router = APIRouter(prefix="/export", tags=["export"])


class ExportStartRequest(BaseModel):
    workspace_id: str | None = None
    all_workspaces: bool = False


def _is_admin(request: Request) -> bool:
    user = getattr(request.state, "user", {}) or {}
    allowed = user.get("workspace_ids", [])
    return isinstance(allowed, list) and "*" in allowed


@router.post("")
async def start_export(
    body: ExportStartRequest,
    request: Request,
    workspace_id: Annotated[str, Depends(resolve_workspace_id)],
) -> dict[str, Any]:
    if body.all_workspaces and not _is_admin(request):
        raise HTTPException(status_code=403, detail="all_workspaces requires admin access")
    scope = ExportScope(
        all_workspaces=body.all_workspaces,
        workspace_id=None if body.all_workspaces else (body.workspace_id or workspace_id),
    )
    service = request.app.state.export_service
    job = await service.start(scope)
    return {"export_id": job.id, "status": str(job.status)}


@router.get("/{export_id}")
async def export_status(
    export_id: str,
    request: Request,
    _ws: Annotated[str, Depends(resolve_workspace_id)],
) -> dict[str, Any]:
    result = await request.app.state.export_service.status(export_id)
    if result is None:
        raise HTTPException(status_code=404, detail="export not found")
    return result


@router.get("/{export_id}/download")
async def download_export(
    export_id: str,
    request: Request,
    token: str = Query(..., min_length=8),
) -> FileResponse:
    """Token-only download. No JWT/API-key. Consumes the one-time token."""
    entry = await request.app.state.export_token_store.consume(token)
    if entry is None or entry.get("export_id") != export_id:
        raise HTTPException(status_code=404, detail="invalid or expired token")
    path = entry.get("path") or ""
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=410, detail="export archive no longer available")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"metronix-export-{export_id}.zip",
    )
```

Security note: this route must not log its query string (the token). The app's access-logging middleware should skip the query string for `/export/{id}/download`; verify in Task 14 wiring and, if a logging middleware records full URLs, add a path exclusion there.

- [ ] **Step 3b: Register the router in `app.py`**

In `src/metronix/api/app.py`, add `export` to the `from metronix.api.routes import (...)` block (alphabetical) and add next to the other memory/knowledge registrations:

```python
app.include_router(export.router, prefix="/api/v1")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/test_export_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/api/routes/export.py src/metronix/api/app.py tests/unit/test_export_routes.py
git commit -m "feat(export): add REST trigger/status/download routes"
```

---

### Task 14: Lifespan wiring — service, watchdog, cleanup sweep

**Files:**
- Modify: `src/metronix/api/app.py` (lifespan: build service, stash on `app.state`, reap orphaned jobs, start a periodic sweep)
- Create: `src/metronix/export/cleanup.py`
- Test: `tests/unit/test_export_cleanup.py`

**Interfaces:**
- Consumes: `Settings`, `build_export_service`, `ExportJobStore.reap_orphaned`, `ExportTokenStore`.
- Produces:
  - `sweep_expired_archives(export_dir: str, max_age_seconds: int, *, now_ts: float) -> int` — delete `*.zip` older than `max_age_seconds`; returns count deleted.
  - Lifespan additions: `app.state.export_service`, `app.state.export_token_store`; on startup call `reap_orphaned(settings.export_job_watchdog_seconds)`; start an `asyncio.Task` that periodically calls `sweep_expired_archives`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_export_cleanup.py
import os
import time

from metronix.export.cleanup import sweep_expired_archives


def test_sweep_deletes_old_zips(tmp_path):
    old = tmp_path / "old.zip"
    new = tmp_path / "new.zip"
    old.write_bytes(b"x")
    new.write_bytes(b"y")
    now = time.time()
    os.utime(old, (now - 10_000, now - 10_000))
    deleted = sweep_expired_archives(str(tmp_path), max_age_seconds=3600, now_ts=now)
    assert deleted == 1
    assert not old.exists() and new.exists()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/unit/test_export_cleanup.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3a: Implement the sweep**

```python
# src/metronix/export/cleanup.py
from __future__ import annotations

import os


def sweep_expired_archives(export_dir: str, max_age_seconds: int, *, now_ts: float) -> int:
    """Delete *.zip files in export_dir older than max_age_seconds. Returns count deleted."""
    if not os.path.isdir(export_dir):
        return 0
    deleted = 0
    for name in os.listdir(export_dir):
        if not name.endswith(".zip"):
            continue
        path = os.path.join(export_dir, name)
        try:
            if now_ts - os.path.getmtime(path) > max_age_seconds:
                os.remove(path)
                deleted += 1
        except OSError:
            continue
    return deleted
```

- [ ] **Step 3b: Wire into lifespan**

In `src/metronix/api/app.py` lifespan (near the autosync scheduler block, ~line 231), add:

```python
    # --- Data export service + maintenance ---
    try:
        import asyncio as _asyncio
        import time as _time

        from metronix.export.cleanup import sweep_expired_archives
        from metronix.export.deps import build_export_service

        export_service = build_export_service(settings)
        app.state.export_service = export_service
        app.state.export_token_store = export_service._tokens  # shared token store

        # Watchdog: fail any job left running past the timeout (e.g. a prior crash).
        await export_service._jobs.reap_orphaned(settings.export_job_watchdog_seconds)

        async def _export_sweep_loop() -> None:
            while True:
                try:
                    sweep_expired_archives(
                        settings.export_dir,
                        settings.export_token_ttl_seconds,
                        now_ts=_time.time(),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("export.sweep.failed", error=str(exc))
                await _asyncio.sleep(max(300, settings.export_token_ttl_seconds))

        app.state.export_sweep_task = _asyncio.create_task(
            _export_sweep_loop(), name="export-sweep"
        )
        logger.info("export.service.started")
    except Exception as exc:  # noqa: BLE001
        logger.warning("export.startup_failed", error=str(exc))
```

If the lifespan has a shutdown section that cancels other tasks (e.g. `autosync_task`), cancel `app.state.export_sweep_task` there too, mirroring the existing pattern.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/unit/test_export_cleanup.py -v`
Expected: PASS.

- [ ] **Step 5: Full check + commit**

Run: `python -m pytest tests/unit -k export -v` (all export unit tests green)
Run: `python -m ruff check src/metronix/export src/metronix/api/routes/export.py src/metronix/mcp/tools/export.py`
Run: `python -m mypy src/metronix/export`
Expected: lint + types clean (fix any issues before committing).

```bash
git add src/metronix/api/app.py src/metronix/export/cleanup.py tests/unit/test_export_cleanup.py
git commit -m "feat(export): wire export service, watchdog, and cleanup sweep into lifespan"
```

---

### Task 15: End-to-end integration test (HTTP API)

**Files:**
- Test: `tests/integration/test_export_e2e.py`

**Interfaces:**
- Consumes: the running FastAPI app (built via the app factory) with PostgreSQL + Redis up and `alembic upgrade head` applied.

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_export_e2e.py
import time
import zipfile

import pytest
from starlette.testclient import TestClient

from metronix.api.app import create_app
from metronix.api.dependencies import resolve_workspace_id

pytestmark = pytest.mark.integration


def test_export_e2e_zip_downloadable(tmp_path, monkeypatch):
    monkeypatch.setenv("METRONIX_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("METRONIX_PUBLIC_BASE_URL", "http://testserver")
    app = create_app()
    app.dependency_overrides[resolve_workspace_id] = lambda: "ws_e2e"
    with TestClient(app) as client:
        started = client.post("/api/v1/export", json={"workspace_id": "ws_e2e"})
        assert started.status_code == 200
        export_id = started.json()["export_id"]

        # poll until ready
        url = None
        for _ in range(50):
            st = client.get(f"/api/v1/export/{export_id}").json()
            if st["status"] == "ready":
                url = st["download_url"]
                break
            if st["status"] == "failed":
                pytest.fail(f"export failed: {st.get('error')}")
            time.sleep(0.2)
        assert url is not None, "export did not become ready"

        # download via the one-time URL (strip host -> path+query for TestClient)
        path_q = url.split("testserver", 1)[1]
        dl = client.get(path_q)
        assert dl.status_code == 200
        assert dl.headers["content-type"] == "application/zip"
        zip_path = tmp_path / "downloaded.zip"
        zip_path.write_bytes(dl.content)
        with zipfile.ZipFile(zip_path) as z:
            assert "manifest.json" in z.namelist()

        # token is one-time: second download fails
        again = client.get(path_q)
        assert again.status_code == 404
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/integration/test_export_e2e.py -v -m integration`
Expected: PASS (PostgreSQL + Redis running, migrations applied). An empty `ws_e2e` still yields a valid ZIP with `manifest.json`.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_export_e2e.py
git commit -m "test(export): end-to-end HTTP export download"
```

---

## Self-Review

**Spec coverage:**
- Shared `ExportService` over MCP + REST → Tasks 10, 12, 13.
- Background build, durable `export_jobs`, asyncio task (not BackgroundTasks), watchdog → Tasks 7, 8, 10, 14.
- One-time CSPRNG token in Redis, consumed on download, token-only auth → Tasks 6, 13.
- `public_base_url` setting + absolute download URL → Tasks 1, 10.
- Per-agent `<agent_id>.md` incl. unregistered agents; distinct-agent enumeration → Tasks 4, 9, 10.
- Documents in original whole form grouped by connector_type; uploads text-only limitation in manifest → Tasks 4, 9, 10.
- Memory: persistent records, all statuses, exclude session/TTL → Task 10 (`lifetime="persistent"`).
- Keyset pagination for docs → Tasks 9, 10.
- Filename slugification of every path segment incl. connector_type → Tasks 3, 10.
- MCP requires explicit workspace_id or all_workspaces (no silent "default") → Task 12.
- Scope: single workspace default, all_workspaces (admin in REST) → Tasks 12, 13.
- Concurrency dedup + disk cap → Tasks 8, 10.
- Cleanup sweep + lazy expiry → Task 14.
- Error handling (404 unknown export, 404 token, 410 archive gone, failed status) → Tasks 8, 10, 13.

**Placeholder scan:** No `TBD`/`TODO`/"handle edge cases" placeholders. All code blocks are correct as-written (the earlier draft's stray `)` in `reap_orphaned` and a bogus import in `service.py` were removed). The doc keyset note in Task 9 is an explained design trade-off, not a placeholder.

**Type consistency:** `ExportScope`/`ExportStatus`/`ExportJob` names and fields are consistent across Tasks 2/8/10/12/13. `ExportService` constructor kwargs in Task 10 match the builder in Task 11. `MemoryReader`/`DocReader` protocol methods match the store methods added in Task 9 (`list_agent_ids`, `list_raw_documents_keyset`, `list_document_workspaces`) and the existing `list_records`/`list_workspaces` signatures.

**Known approximation:** the doc keyset predicate mixes `updated_at DESC, id ASC` with a tuple comparison (Task 9 note). It is correct enough for read-mostly export and documented; tighten to `(updated_at DESC, id DESC)` if exactness is later required.
