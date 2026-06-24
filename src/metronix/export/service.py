from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

import structlog
from sqlalchemy.exc import IntegrityError

from metronix.export.archive import ExportArchiveWriter
from metronix.export.models import ExportJob, ExportScope, ExportStatus
from metronix.export.render import (
    build_manifest,
    render_agent_memory,
    render_document,
    unique_slug,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine

    from metronix.core.models import MemoryRecord, RawDocument

logger = structlog.get_logger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    """Schedule a background build task and keep a strong reference to it."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


_MEM_PAGE = 500
_DOC_PAGE = 200
_CAP_CHECK_EVERY = 100
_LIMITATIONS = [
    "Uploaded files are exported as extracted text only; "
    "original binary files are not retained by Metronix.",
]


class MemoryReader(Protocol):
    async def list_workspaces(self) -> list[str]:
        """Return all workspace ids that have memory."""

    async def list_agent_ids(self, ws: str) -> list[str]:
        """Return distinct agent ids with memory in a workspace (incl. unregistered)."""

    async def list_records(
        self, ws: str, *, agent_id: str, lifetime: str, limit: int, offset: int
    ) -> list[MemoryRecord]:
        """Return a page of memory records for an agent."""


class DocReader(Protocol):
    async def list_document_workspaces(self) -> list[str]:
        """Return all workspace ids that have ingested documents."""

    async def list_raw_documents_keyset(
        self, ws: str, *, after_updated_at: Any, after_id: str | None, limit: int
    ) -> list[RawDocument]:
        """Return a keyset page of raw documents for a workspace."""


class RegisteredAgents(Protocol):
    async def registered_agent_ids(self, ws: str) -> set[str]:
        """Return the set of agent ids registered in the agents table."""


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
        schedule: Callable[[Coroutine[Any, Any, None]], None] | None = None,
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
        self._schedule = schedule or (lambda coro: _spawn(coro))

    @property
    def token_store(self) -> Any:
        """Public accessor for the one-time download token store (used by the route)."""
        return self._tokens

    async def get_job(self, export_id: str) -> ExportJob | None:
        """Fetch the raw job (lets the REST layer authorize against its scope)."""
        job: ExportJob | None = await self._jobs.get(export_id)
        return job

    async def reap_orphaned_jobs(self, older_than_seconds: int) -> int:
        """Fail jobs stuck running past the watchdog window (called on startup)."""
        result: int = await self._jobs.reap_orphaned(older_than_seconds)
        return result

    async def start(self, scope: ExportScope) -> ExportJob:
        if not scope.all_workspaces and not scope.workspace_id:
            raise ValueError("workspace_id is required unless all_workspaces is set")
        existing: ExportJob | None = await self._jobs.find_active_for_scope(scope)
        if existing is not None:
            return existing
        if self._cap and await asyncio.to_thread(self._dir_size) >= self._cap:
            raise RuntimeError("export disk cap exceeded; try again after cleanup")
        job = ExportJob(
            id=self._new_id(),
            scope=scope,
            status=ExportStatus.PENDING,
            created_at=self._now(),
            updated_at=self._now(),
        )
        try:
            await self._jobs.create(job)
        except IntegrityError:
            # Lost the race against a concurrent start for the same scope — the
            # unique partial index rejected this insert. Return the winner.
            winner: ExportJob | None = await self._jobs.find_active_for_scope(scope)
            if winner is not None:
                return winner
            raise
        self._schedule(self._build_guarded(job.id, scope))
        return job

    async def status(self, export_id: str) -> dict[str, Any] | None:
        job: ExportJob | None = await self._jobs.get(export_id)
        if job is None:
            return None
        out: dict[str, Any] = {
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
        # Token is minted once at build completion and stored on the job; status
        # reuses it so repeated polling does not create many valid tokens.
        if job.status == ExportStatus.READY and job.download_token:
            out["download_url"] = (
                f"{self._base}/api/v1/export/{job.id}/download?token={job.download_token}"
            )
        return out

    def _dir_size(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self._dir):
            for f in files:
                with contextlib.suppress(OSError):
                    total += os.path.getsize(os.path.join(root, f))
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
        agent_manifest: list[dict[str, Any]] = []
        n_agents = n_mem = n_docs = 0

        with ExportArchiveWriter(path) as zw:
            n_writes = 0

            async def write(arcname: str, text: str) -> None:
                # zipfile compression is CPU-bound; run it off the event loop so a
                # large export does not block the API. Writes are serialized (one
                # to_thread at a time), so the single ZipFile stays safe.
                nonlocal n_writes
                await asyncio.to_thread(zw.write_text, arcname, text)
                n_writes += 1
                # Best-effort disk-cap guard during the build, not only at start().
                if self._cap and n_writes % _CAP_CHECK_EVERY == 0:
                    size = await asyncio.to_thread(os.path.getsize, path)
                    if size >= self._cap:
                        raise RuntimeError("export exceeded disk cap during build")

            for ws in workspaces:
                registered = await self._registry.registered_agent_ids(ws)
                used: set[str] = set()
                for agent_id in await self._memory.list_agent_ids(ws):
                    records = await self._collect_records(ws, agent_id)
                    fname = unique_slug(agent_id, used) + ".md"
                    arc = f"{ws}/memory/{fname}"
                    await write(arc, render_agent_memory(agent_id, ws, records))
                    agent_manifest.append(
                        {
                            "agent_id": agent_id,
                            "workspace_id": ws,
                            "file": arc,
                            "registered": agent_id in registered,
                            "record_count": len(records),
                        }
                    )
                    n_agents += 1
                    n_mem += len(records)

                doc_used: dict[str, set[str]] = {}
                async for doc in self._iter_docs(ws):
                    ct = unique_slug(doc.connector_type or "unknown", set(), max_len=40)
                    used_for_ct = doc_used.setdefault(ct, set())
                    base = doc.source_id or doc.title or doc.id
                    fname = unique_slug(base, used_for_ct) + ".md"
                    await write(f"{ws}/documents/{ct}/{fname}", render_document(doc))
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
            await write(
                "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )

        token = await self._tokens.mint(export_id, path)
        await self._jobs.set_result(
            export_id,
            workspace_count=len(workspaces),
            agent_count=n_agents,
            memory_record_count=n_mem,
            document_count=n_docs,
            size_bytes=zw.size_bytes,
            archive_path=path,
            download_token=token,
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

    async def _iter_docs(self, ws: str) -> AsyncIterator[RawDocument]:
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
