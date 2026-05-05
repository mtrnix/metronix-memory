"""MemorySnapshotService — JSONL+gzip backup/restore for agent memory (MTRNIX-272).

L3 service. Wraps :class:`MemoryPostgresStore` (metadata + transactional replace),
:class:`MemoryQdrantStore` (re-embedding on restore), and the Neo4j memory graph
helpers (best-effort cleanup + re-population).

Snapshot file layout (under ``settings.snapshot_dir``):

    {workspace_id}/{agent_id}/{snapshot_id}.jsonl.gz
    {workspace_id}/{agent_id}/{snapshot_id}.sha256

The gzip body is self-describing — line 1 is a manifest, lines 2..N are
serialised :class:`MemoryRecord` JSON.  The sidecar holds the SHA-256 hex digest
so callers can verify integrity before reading the gzip body.

**Embeddings are intentionally NOT stored in the snapshot.** On restore each
record goes through :meth:`MemoryQdrantStore.upsert` which re-embeds via the
configured embedding provider — keeps the file portable across embedding-model
versions at the cost of a slower restore.

PG is the source of truth — Qdrant + Neo4j are best-effort during restore.
A failure populating downstream stores is logged but never fails the restore;
the next memory write or scheduled scan reconciles them.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from metatron.core.events import MEMORY_RESTORED, MEMORY_SNAPSHOT_CREATED
from metatron.core.exceptions import (
    MemoryNotFoundError,
    SnapshotCorruptError,
    SnapshotOverflowError,
)
from metatron.core.models import (
    LifecycleStatus,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySnapshot,
)
from metatron.storage.memory_graph import (
    delete_memory_node as _graph_delete_memory_node,
)
from metatron.storage.memory_graph import (
    save_memory_to_graph as _graph_save_memory,
)

if TYPE_CHECKING:
    from metatron.core.events import EventBus
    from metatron.storage.memory_postgres import MemoryPostgresStore
    from metatron.storage.memory_qdrant import MemoryQdrantStore

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


_MANIFEST_VERSION = 1
_LIST_PAGE_LIMIT = 10_000


class SnapshotTrigger(StrEnum):
    """How a snapshot came to be — written to ``memory_snapshots.trigger``."""

    MANUAL = "manual"
    PRE_RESET = "pre_reset"
    PRE_RESTORE = "pre_restore"


class DiffKey(StrEnum):
    """Diff key strategy used by :meth:`MemorySnapshotService.diff`."""

    SOURCE = "source"
    CONTENT_HASH = "content_hash"


@dataclass
class SnapshotDiff:
    """Result of comparing two snapshots of the same agent.

    ``added``     — record ids present in ``to`` but not ``from``.
    ``removed``   — record ids present in ``from`` but not ``to``.
    ``changed``   — same diff key but different ``content_hash``. Always empty
                    when ``key=content_hash`` (tautological).
    """

    from_snapshot_id: str = ""
    to_snapshot_id: str = ""
    key: str = DiffKey.SOURCE.value
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _from_iso(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(raw))


def _record_to_json(record: MemoryRecord) -> dict[str, Any]:
    """Serialise MemoryRecord (incl. lifecycle fields) to a JSON-friendly dict."""
    return {
        "id": record.id,
        "workspace_id": record.workspace_id,
        "agent_id": record.agent_id,
        "scope": record.scope.value,
        "kind": record.kind.value,
        "source_type": record.source_type,
        "content": record.content,
        "tags": list(record.tags),
        "importance_score": record.importance_score,
        "ttl_expires_at": _iso(record.ttl_expires_at),
        "content_hash": record.content_hash,
        "session_id": record.session_id,
        "metadata": dict(record.metadata),
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
        "status": record.status.value,
        "freshness_score": record.freshness_score,
        "superseded_by": record.superseded_by,
        "valid_from": _iso(record.valid_from),
        "valid_until": _iso(record.valid_until),
        "evidence_count": record.evidence_count,
        "verification_state": record.verification_state,
    }


def _record_from_json(payload: dict[str, Any]) -> MemoryRecord:
    """Inverse of :func:`_record_to_json`. Tolerates missing optional fields."""
    return MemoryRecord(
        id=str(payload["id"]),
        workspace_id=str(payload["workspace_id"]),
        agent_id=str(payload["agent_id"]),
        scope=MemoryScope(payload.get("scope", MemoryScope.PER_AGENT.value)),
        kind=MemoryKind(payload.get("kind", MemoryKind.FACT.value)),
        source_type=str(payload.get("source_type", "")),
        content=str(payload.get("content", "")),
        tags=list(payload.get("tags") or []),
        importance_score=float(payload.get("importance_score", 0.5)),
        ttl_expires_at=_from_iso(payload.get("ttl_expires_at")),
        content_hash=str(payload.get("content_hash", "")),
        created_at=_from_iso(payload.get("created_at")) or datetime.now(UTC),
        session_id=payload.get("session_id"),
        metadata=dict(payload.get("metadata") or {}),
        status=LifecycleStatus(payload.get("status", LifecycleStatus.ACTIVE.value)),
        freshness_score=float(payload.get("freshness_score", 0.5)),
        superseded_by=payload.get("superseded_by"),
        valid_from=_from_iso(payload.get("valid_from")),
        valid_until=_from_iso(payload.get("valid_until")),
        evidence_count=int(payload.get("evidence_count", 0)),
        verification_state=payload.get("verification_state"),
        updated_at=_from_iso(payload.get("updated_at")),
    )


def _diff_key(record: MemoryRecord, key: DiffKey) -> str:
    """Compute the diff key for a record per the chosen strategy.

    Three distinct prefixes are emitted (``hash::`` for ``CONTENT_HASH``;
    ``src::`` and ``id::`` for ``SOURCE``) so a record whose ``source_type``
    happens to be the literal string ``"id"`` or ``"hash"`` cannot collide
    with a fallback-keyed record.
    """
    if key == DiffKey.CONTENT_HASH:
        return f"hash::{record.content_hash or record.id}"
    # SOURCE — fall back to id when the source pair is unset so unscoped
    # records still appear in the diff (matched only by exact id).
    source_id = (record.metadata or {}).get("source_id") or ""
    if record.source_type and source_id:
        return f"src::{record.source_type}:{source_id}"
    return f"id::{record.id}"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MemorySnapshotService:
    """Per-workspace orchestrator for snapshot/restore/diff operations."""

    def __init__(
        self,
        pg_store: MemoryPostgresStore,
        qdrant_store: MemoryQdrantStore,
        *,
        workspace_id: str,
        snapshot_dir: Path | str,
        event_bus: EventBus | None = None,
        max_file_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self._pg = pg_store
        self._qdrant = qdrant_store
        self._workspace_id = workspace_id
        self._snapshot_dir = Path(snapshot_dir)
        self._event_bus = event_bus
        self._max_file_bytes = max_file_bytes
        self._warned_no_bus = False

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _agent_dir(self, agent_id: str) -> Path:
        return self._snapshot_dir / self._workspace_id / agent_id

    def _file_path(self, agent_id: str, snapshot_id: str) -> Path:
        return self._agent_dir(agent_id) / f"{snapshot_id}.jsonl.gz"

    def _sha_path(self, agent_id: str, snapshot_id: str) -> Path:
        return self._agent_dir(agent_id) / f"{snapshot_id}.sha256"

    async def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self._event_bus is None:
            if not self._warned_no_bus:
                logger.warning(
                    "event_bus_not_wired",
                    service="MemorySnapshotService",
                    workspace_id=self._workspace_id,
                )
                self._warned_no_bus = True
            return
        try:
            await self._event_bus.emit(name, payload)
        except Exception:  # noqa: BLE001 — event delivery is best-effort
            logger.warning("snapshot_service.bus_emit_failed", event=name, exc_info=True)

    # ------------------------------------------------------------------
    # File IO (sync, run via to_thread)
    # ------------------------------------------------------------------

    def _write_snapshot_file_sync(
        self,
        target: Path,
        manifest: dict[str, Any],
        records: list[MemoryRecord],
    ) -> tuple[str, int]:
        """Write the gzip body atomically. Returns (sha256_hex, size_bytes).

        Streams to a tmp file in the same directory, then atomic-renames so a
        crash mid-write never leaves a half-finished snapshot under the final
        name. SHA-256 is computed over the gzip bytes (i.e. the on-disk body),
        not the JSONL plaintext, so callers can verify integrity by hashing
        the file alone.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        size = 0

        # delete=False: we close, hash, then atomically rename.
        with tempfile.NamedTemporaryFile(
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as raw:
            tmp_path = Path(raw.name)
            try:
                with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
                    payload = json.dumps(manifest, ensure_ascii=False) + "\n"
                    gz.write(payload.encode("utf-8"))
                    for record in records:
                        line = json.dumps(_record_to_json(record), ensure_ascii=False) + "\n"
                        gz.write(line.encode("utf-8"))
                raw.flush()
                # fsync is inside the try so a failing fsync still triggers
                # tmp cleanup — otherwise we'd leak a partial file on disk.
                os.fsync(raw.fileno())
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise

        size = tmp_path.stat().st_size
        if size > self._max_file_bytes:
            tmp_path.unlink(missing_ok=True)
            raise SnapshotOverflowError(
                f"snapshot exceeds {self._max_file_bytes} bytes (got {size})"
            )

        # Compute SHA-256 over the on-disk gzip bytes.
        with tmp_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(64 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()

        # Atomic rename of the gzip body.
        os.replace(tmp_path, target)
        # Sidecar path mirrors :meth:`_sha_path` — strip the full ``.jsonl.gz``
        # suffix pair so the cleanup path on PG-save failure finds the same
        # file we wrote here.
        sidecar = target.with_name(target.name.replace(".jsonl.gz", ".sha256"))
        # Atomic sidecar write — write to ``.tmp`` next to the final name and
        # rename. A crash between the gzip rename and the sidecar rename leaves
        # NO half-written sidecar; the read path treats a missing sidecar as
        # "verify against the PG-row checksum only" (still mandatory).
        tmp_sidecar = sidecar.with_name(sidecar.name + ".tmp")
        tmp_sidecar.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
        os.replace(tmp_sidecar, sidecar)
        return digest, size

    def _read_snapshot_file_sync(
        self,
        source: Path,
        sidecar: Path,
        expected_digest: str,
    ) -> tuple[dict[str, Any], list[MemoryRecord]]:
        """Verify SHA-256 then read manifest + records from the gzip body."""
        if not source.is_file():
            raise SnapshotCorruptError(f"snapshot file missing: {source}")

        # Recompute digest on the raw gzip bytes.
        hasher = hashlib.sha256()
        size = 0
        with source.open("rb") as fh:
            for chunk in iter(lambda: fh.read(64 * 1024), b""):
                hasher.update(chunk)
                size += len(chunk)
                if size > self._max_file_bytes:
                    raise SnapshotOverflowError(
                        f"snapshot exceeds {self._max_file_bytes} bytes — refusing to read"
                    )
        actual = hasher.hexdigest()

        if expected_digest and actual != expected_digest:
            raise SnapshotCorruptError(
                f"snapshot checksum mismatch: expected {expected_digest!r}, got {actual!r}"
            )

        # Cross-check sidecar when present (defence in depth — protects against
        # a tampered ``memory_snapshots.content_hash`` row paired with an
        # equally tampered file).
        if sidecar.is_file():
            try:
                first_token = sidecar.read_text(encoding="utf-8").strip().split()[0]
            except Exception as exc:
                raise SnapshotCorruptError(f"sidecar unreadable: {exc}") from exc
            if first_token != actual:
                raise SnapshotCorruptError(
                    f"sidecar checksum mismatch: sidecar={first_token!r} actual={actual!r}"
                )

        # Now read the body.
        manifest: dict[str, Any] | None = None
        records: list[MemoryRecord] = []
        with gzip.open(source, "rt", encoding="utf-8") as gz:
            for raw_line in gz:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SnapshotCorruptError(f"snapshot has invalid JSON: {exc}") from exc
                if manifest is None:
                    if obj.get("_kind") != "manifest":
                        raise SnapshotCorruptError("snapshot is missing manifest line")
                    manifest = obj
                else:
                    records.append(_record_from_json(obj))

        if manifest is None:
            raise SnapshotCorruptError("snapshot is empty")
        return manifest, records

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create(
        self,
        agent_id: str,
        *,
        label: str = "",
        trigger: SnapshotTrigger | str = SnapshotTrigger.MANUAL,
    ) -> MemorySnapshot:
        """Export current memory for ``agent_id`` to a JSONL+gzip file.

        ``label`` is a free-form name surfaced in the UI / Jira logs.
        ``trigger`` records *why* the snapshot was taken — set automatically by
        :meth:`reset` and :meth:`restore` to ``pre_reset`` / ``pre_restore``.
        """
        if not agent_id:
            raise ValueError("agent_id is required")
        trigger_str = trigger.value if isinstance(trigger, SnapshotTrigger) else str(trigger)

        # +1 sentinel so we can detect overflow vs an exact match. Pagination
        # for snapshots > 10k records is a planned follow-up; until it lands,
        # we refuse rather than silently truncate the export.
        records = await self._pg.list_records(
            self._workspace_id,
            agent_id=agent_id,
            limit=_LIST_PAGE_LIMIT + 1,
        )
        if len(records) > _LIST_PAGE_LIMIT:
            raise SnapshotOverflowError(
                f"snapshot would exceed {_LIST_PAGE_LIMIT} records "
                f"(found at least {len(records)} for agent {agent_id!r}) — "
                "pagination not yet supported"
            )

        snapshot = MemorySnapshot(
            workspace_id=self._workspace_id,
            agent_id=agent_id,
            label=label,
            trigger=trigger_str,
            record_count=len(records),
            created_at=datetime.now(UTC),
        )
        target = self._file_path(agent_id, snapshot.id)
        manifest = {
            "_kind": "manifest",
            "version": _MANIFEST_VERSION,
            "snapshot_id": snapshot.id,
            "workspace_id": snapshot.workspace_id,
            "agent_id": snapshot.agent_id,
            "label": snapshot.label,
            "trigger": snapshot.trigger,
            "record_count": snapshot.record_count,
            "created_at": _iso(snapshot.created_at),
        }

        digest, size = await asyncio.to_thread(
            self._write_snapshot_file_sync, target, manifest, records
        )
        snapshot.content_hash = digest
        snapshot.size_bytes = size
        # Store a path relative to the snapshot root. The actual file path is
        # always reconstructed from :meth:`_file_path` on read; this column is
        # informational (UI / log breadcrumbs / future cleanup tooling). Using
        # a relative form keeps the row valid if the deployment moves
        # ``METATRON_SNAPSHOT_DIR`` to a new mount.
        snapshot.storage_path = f"{self._workspace_id}/{snapshot.agent_id}/{snapshot.id}.jsonl.gz"

        try:
            await self._pg.save_snapshot(snapshot)
        except Exception:
            # Roll back the file write so we don't leave an orphan on disk.
            target.unlink(missing_ok=True)
            self._sha_path(agent_id, snapshot.id).unlink(missing_ok=True)
            raise

        await self._emit(
            MEMORY_SNAPSHOT_CREATED,
            {
                "workspace_id": self._workspace_id,
                "agent_id": agent_id,
                "snapshot_id": snapshot.id,
                "trigger": snapshot.trigger,
                "record_count": snapshot.record_count,
            },
        )
        logger.info(
            "snapshot_service.created",
            workspace_id=self._workspace_id,
            agent_id=agent_id,
            snapshot_id=snapshot.id,
            trigger=snapshot.trigger,
            record_count=snapshot.record_count,
            size_bytes=size,
        )
        return snapshot

    async def get(self, snapshot_id: str) -> MemorySnapshot:
        """Fetch a snapshot row by id. 404 → :class:`MemoryNotFoundError`."""
        row = await self._pg.get_snapshot(self._workspace_id, snapshot_id)
        if row is None:
            raise MemoryNotFoundError(f"snapshot not found: {snapshot_id}")
        return row

    async def list_snapshots(self, agent_id: str) -> list[MemorySnapshot]:
        """List snapshots for an agent, newest first.

        Named ``list_snapshots`` rather than ``list`` so it does not shadow
        the built-in ``list`` inside type annotations on sibling methods.
        """
        return await self._pg.list_snapshots(self._workspace_id, agent_id)

    async def restore(self, snapshot_id: str) -> tuple[MemorySnapshot, int]:
        """Restore the given snapshot.

        Steps:
          1. Look up the snapshot row (workspace-scoped — 404 leaks nothing).
          2. Verify SHA-256 of the file against the stored ``content_hash``
             (and the sidecar when present).
          3. Sanity-check the manifest matches the row.
          4. Take an automatic ``pre_restore`` snapshot of the current agent
             state — gives the operator a one-step undo.
          5. PG ``BEGIN; DELETE … WHERE agent_id = ?; INSERT …; COMMIT``.
          6. Best-effort downstream cleanup + repopulation in Qdrant + Neo4j.
          7. Emit ``MEMORY_RESTORED``.

        Returns ``(pre_restore_snapshot, restored_count)``.

        Caveats (see follow-up issues for the v2 fixes):

        * **Sequential, synchronous** — Qdrant ``upsert`` (re-embeds via the
          embedding provider) and Neo4j ``save_memory_to_graph`` run one
          record at a time.  A few hundred records is fine over a typical
          HTTP request; tens of thousands will exceed the gateway timeout.
          Track via the planned async-restore follow-up.
        * **No per-(workspace, agent) lock** — concurrent restores for the
          same agent are safe in PG (transactional replace) but downstream
          stores can interleave, leaving Qdrant/Neo4j temporarily showing a
          mixture of both restores until the next memory write reconciles.
          Operator-facing endpoint, low real-world concurrency; if needed,
          gate behind a Redis lock keyed on ``(workspace_id, agent_id)``.
        """
        snapshot = await self.get(snapshot_id)

        # Always derive the file path from the canonical layout, not the
        # ``storage_path`` column — defence against a tampered PG row.
        # The manifest + checksum checks would catch a swap, but reading
        # an attacker-chosen path is a needless first-step risk.
        source = self._file_path(snapshot.agent_id, snapshot.id)
        sidecar = self._sha_path(snapshot.agent_id, snapshot.id)

        manifest, records = await asyncio.to_thread(
            self._read_snapshot_file_sync, source, sidecar, snapshot.content_hash
        )

        if (
            manifest.get("workspace_id") != snapshot.workspace_id
            or manifest.get("agent_id") != snapshot.agent_id
            or manifest.get("snapshot_id") != snapshot.id
        ):
            raise SnapshotCorruptError(
                "manifest does not match snapshot row "
                f"(row=({snapshot.workspace_id}, {snapshot.agent_id}, {snapshot.id}), "
                f"manifest=({manifest.get('workspace_id')}, "
                f"{manifest.get('agent_id')}, {manifest.get('snapshot_id')}))"
            )
        if manifest.get("record_count") != len(records):
            raise SnapshotCorruptError(
                f"manifest record_count={manifest.get('record_count')} but "
                f"file contains {len(records)} records"
            )

        # 4. Pre-restore auto-snapshot (skipped silently when there's nothing
        # to back up — first restore on a fresh agent has zero records).
        pre_restore = await self.create(
            snapshot.agent_id,
            label=f"pre-restore of {snapshot.id}",
            trigger=SnapshotTrigger.PRE_RESTORE,
        )

        # 5. Transactional replace in PG. ``replace_for_agent`` raises
        # ValueError if any record has a mismatched workspace_id / agent_id —
        # that means the file passed checksum + manifest checks but still
        # contains foreign records. Surface this as a corruption error rather
        # than a generic 500.
        try:
            deleted_ids, inserted_count = await self._pg.replace_for_agent(
                self._workspace_id, snapshot.agent_id, records
            )
        except ValueError as exc:
            raise SnapshotCorruptError(
                f"snapshot file contains records with mismatched workspace/agent: {exc}"
            ) from exc

        # 6. Best-effort downstream stores. We never fail the restore here —
        # PG is the source of truth and search is reconciled lazily.
        # Both Qdrant and Neo4j use per-id deletes from the authoritative
        # ``deleted_ids`` returned by PG ``DELETE … RETURNING`` — matches the
        # pattern in ``MemoryService.reset`` and avoids the over-delete bug
        # of Qdrant's ``delete_by_agent``.
        for rid in deleted_ids:
            try:
                await self._qdrant.delete(rid)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "snapshot_service.qdrant_delete_failed", record_id=rid, exc_info=True
                )
            try:
                await asyncio.to_thread(_graph_delete_memory_node, self._workspace_id, rid)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "snapshot_service.graph_delete_failed", record_id=rid, exc_info=True
                )

        for record in records:
            try:
                await self._qdrant.upsert(record)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "snapshot_service.qdrant_upsert_failed", record_id=record.id, exc_info=True
                )
            try:
                await asyncio.to_thread(_graph_save_memory, record)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "snapshot_service.graph_save_failed", record_id=record.id, exc_info=True
                )

        await self._emit(
            MEMORY_RESTORED,
            {
                "workspace_id": self._workspace_id,
                "agent_id": snapshot.agent_id,
                "snapshot_id": snapshot.id,
                "record_count": inserted_count,
                "pre_restore_snapshot_id": pre_restore.id,
            },
        )
        logger.info(
            "snapshot_service.restored",
            workspace_id=self._workspace_id,
            agent_id=snapshot.agent_id,
            snapshot_id=snapshot.id,
            restored=inserted_count,
            pre_restore_snapshot_id=pre_restore.id,
        )
        return pre_restore, inserted_count

    async def diff(
        self,
        from_snapshot_id: str,
        to_snapshot_id: str,
        *,
        key: DiffKey | str = DiffKey.SOURCE,
    ) -> SnapshotDiff:
        """Compare two snapshots of the same agent.

        Both snapshots must be in the bound workspace and share an
        ``agent_id``. Mismatches raise :class:`ValueError` (route maps to 400).
        """
        if from_snapshot_id == to_snapshot_id:
            raise ValueError("diff requires two distinct snapshot ids")
        try:
            key_kind = DiffKey(key) if not isinstance(key, DiffKey) else key
        except ValueError as exc:
            raise ValueError(f"unknown diff key: {key!r}") from exc

        from_snap = await self.get(from_snapshot_id)
        to_snap = await self.get(to_snapshot_id)
        if from_snap.agent_id != to_snap.agent_id:
            raise ValueError(
                "diff requires same-agent snapshots "
                f"(from.agent_id={from_snap.agent_id!r}, to.agent_id={to_snap.agent_id!r})"
            )

        from_records = await self._load_records(from_snap)
        to_records = await self._load_records(to_snap)

        # key -> (record_id, content_hash)
        def _index(records: list[MemoryRecord]) -> dict[str, tuple[str, str]]:
            out: dict[str, tuple[str, str]] = {}
            for rec in records:
                out[_diff_key(rec, key_kind)] = (rec.id, rec.content_hash or "")
            return out

        from_idx = _index(from_records)
        to_idx = _index(to_records)

        added: list[str] = sorted(rid for k, (rid, _h) in to_idx.items() if k not in from_idx)
        removed: list[str] = sorted(rid for k, (rid, _h) in from_idx.items() if k not in to_idx)
        changed: list[str] = []
        if key_kind == DiffKey.SOURCE:
            for k, (rid, h) in to_idx.items():
                prior = from_idx.get(k)
                if prior is not None and prior[1] != h:
                    changed.append(rid)
            changed.sort()

        return SnapshotDiff(
            from_snapshot_id=from_snapshot_id,
            to_snapshot_id=to_snapshot_id,
            key=key_kind.value,
            added=added,
            removed=removed,
            changed=changed,
        )

    async def _load_records(self, snapshot: MemorySnapshot) -> list[MemoryRecord]:
        """Read+verify+parse a snapshot file. Used by :meth:`diff`.

        Path is derived from canonical layout (not ``snapshot.storage_path``)
        to match :meth:`restore` — see the comment there.
        """
        source = self._file_path(snapshot.agent_id, snapshot.id)
        sidecar = self._sha_path(snapshot.agent_id, snapshot.id)
        _manifest, records = await asyncio.to_thread(
            self._read_snapshot_file_sync, source, sidecar, snapshot.content_hash
        )
        return records

    async def read_records(
        self,
        snapshot_id: str,
        *,
        ids: list[str] | None = None,
    ) -> list[MemoryRecord]:
        """Read records from a snapshot file, optionally filtered by id.

        Built for the diff-UI flow: ``GET /snapshots/diff`` returns only id
        lists, and the FE lazily resolves visible ids to full records.
        Reading from the snapshot file (rather than ``GET /memory/records``)
        is mandatory — ``removed`` records may no longer exist in live
        memory, and ``changed`` records would return the *current* version
        instead of the snapshot-time version.

        Service-level contract:

        * ``ids=None`` returns every record in the file. The HTTP route
          does NOT expose this mode — it is kept only for in-process /
          test callers.
        * ``ids=[]`` returns an empty list (distinct from ``None``).
        * Unknown ids are silently dropped — the caller already knows
          what it asked for and can surface the gap if needed.

        File is SHA-256 verified by :meth:`_load_records` before parsing.
        """
        snapshot = await self.get(snapshot_id)
        records = await self._load_records(snapshot)
        if ids is None:
            returned = records
        else:
            wanted = set(ids)
            returned = [r for r in records if r.id in wanted]
        logger.info(
            "snapshot_service.records_read",
            workspace_id=self._workspace_id,
            agent_id=snapshot.agent_id,
            snapshot_id=snapshot.id,
            requested_ids_count=len(ids) if ids is not None else None,
            returned_count=len(returned),
            file_record_count=len(records),
        )
        return returned
