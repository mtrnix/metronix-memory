"""Tests for MemorySnapshotService (MTRNIX-272)."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

if TYPE_CHECKING:
    from pathlib import Path

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
from metatron.memory.snapshot import (
    DiffKey,
    MemorySnapshotService,
    SnapshotTrigger,
)


def _record(
    record_id: str,
    *,
    agent_id: str = "agent1",
    workspace_id: str = "ws1",
    content: str = "",
    content_hash: str = "",
    source_type: str = "",
    source_id: str = "",
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        scope=MemoryScope.PER_AGENT,
        kind=MemoryKind.FACT,
        source_type=source_type,
        content=content or f"content of {record_id}",
        tags=["t1"],
        importance_score=0.7,
        content_hash=content_hash or f"hash-of-{record_id}",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
        metadata={"source_id": source_id} if source_id else {},
        status=LifecycleStatus.ACTIVE,
    )


def _snapshot_row(
    *,
    snapshot_id: str,
    agent_id: str,
    workspace_id: str,
    storage_path: str,
    content_hash: str,
    record_count: int,
    label: str = "",
    trigger: str = SnapshotTrigger.MANUAL.value,
    size_bytes: int = 0,
) -> MemorySnapshot:
    return MemorySnapshot(
        id=snapshot_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        label=label,
        trigger=trigger,
        record_count=record_count,
        content_hash=content_hash,
        size_bytes=size_bytes,
        storage_path=storage_path,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


@pytest.fixture
def service_factory(tmp_path: Path):
    """Build a MemorySnapshotService with mocked pg/qdrant stores."""

    def _make(
        workspace_id: str = "ws1",
        max_file_bytes: int = 256 * 1024 * 1024,
    ) -> tuple[MemorySnapshotService, AsyncMock, AsyncMock]:
        pg = AsyncMock()
        qdrant = AsyncMock()
        # Default: no records in PG.
        pg.list_records.return_value = []
        # Default: save_snapshot returns the input untouched.
        pg.save_snapshot.side_effect = lambda s: s
        # Default: replace_for_agent reports no deletes, the inserted count.
        pg.replace_for_agent.side_effect = lambda ws, ag, recs: ([], len(recs))
        service = MemorySnapshotService(
            pg_store=pg,
            qdrant_store=qdrant,
            workspace_id=workspace_id,
            snapshot_dir=tmp_path,
            max_file_bytes=max_file_bytes,
        )
        return service, pg, qdrant

    return _make


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_writes_jsonl_gz_and_sidecar(self, service_factory, tmp_path: Path) -> None:
        service, pg, _ = service_factory()
        pg.list_records.return_value = [_record("r1"), _record("r2")]

        snapshot = await service.create("agent1", label="manual snap")

        target = tmp_path / "ws1" / "agent1" / f"{snapshot.id}.jsonl.gz"
        sidecar = tmp_path / "ws1" / "agent1" / f"{snapshot.id}.sha256"
        assert target.is_file()
        assert sidecar.is_file()
        assert snapshot.record_count == 2
        assert snapshot.size_bytes > 0
        assert snapshot.content_hash, "content_hash must be set"
        # Sidecar starts with the same digest.
        assert sidecar.read_text(encoding="utf-8").startswith(snapshot.content_hash)

    async def test_writes_manifest_as_first_line(self, service_factory, tmp_path: Path) -> None:
        service, pg, _ = service_factory()
        pg.list_records.return_value = [_record("r1")]

        snapshot = await service.create("agent1")

        # storage_path is relative to the snapshot root since MTRNIX-272 v2.
        target = tmp_path / snapshot.storage_path
        with gzip.open(target, "rt", encoding="utf-8") as fh:
            lines = fh.readlines()
        assert len(lines) == 2  # manifest + 1 record
        manifest = json.loads(lines[0])
        assert manifest["_kind"] == "manifest"
        assert manifest["agent_id"] == "agent1"
        assert manifest["workspace_id"] == "ws1"
        assert manifest["snapshot_id"] == snapshot.id
        assert manifest["record_count"] == 1
        body = json.loads(lines[1])
        assert body["id"] == "r1"
        assert body["status"] == "active"

    async def test_persists_metadata_row(self, service_factory) -> None:
        service, pg, _ = service_factory()
        pg.list_records.return_value = []

        snapshot = await service.create("agent1", trigger=SnapshotTrigger.PRE_RESET)

        pg.save_snapshot.assert_awaited_once()
        saved = pg.save_snapshot.await_args.args[0]
        assert saved.id == snapshot.id
        assert saved.agent_id == "agent1"
        assert saved.workspace_id == "ws1"
        assert saved.trigger == SnapshotTrigger.PRE_RESET.value
        assert saved.content_hash == snapshot.content_hash

    async def test_rolls_back_file_when_pg_save_fails(
        self, service_factory, tmp_path: Path
    ) -> None:
        service, pg, _ = service_factory()
        pg.list_records.return_value = [_record("r1")]
        pg.save_snapshot.side_effect = RuntimeError("pg down")

        with pytest.raises(RuntimeError, match="pg down"):
            await service.create("agent1")

        # No leftover gzip + sidecar.
        agent_dir = tmp_path / "ws1" / "agent1"
        assert not any(agent_dir.glob("*.jsonl.gz"))
        assert not any(agent_dir.glob("*.sha256"))

    async def test_rejects_oversized_file(self, service_factory) -> None:
        service, pg, _ = service_factory(max_file_bytes=10)
        pg.list_records.return_value = [_record("r1", content="x" * 10_000)]

        # Oversize is an "overflow" condition, not corruption — see
        # SnapshotOverflowError vs SnapshotCorruptError split in core/exceptions.
        with pytest.raises(SnapshotOverflowError, match="exceeds"):
            await service.create("agent1")
        pg.save_snapshot.assert_not_awaited()

    async def test_create_rejects_empty_agent_id(self, service_factory) -> None:
        service, _, _ = service_factory(workspace_id="ws1")
        with pytest.raises(ValueError, match="agent_id is required"):
            await service.create("")

    async def test_refuses_when_pg_returns_more_than_10k(self, service_factory) -> None:
        service, pg, _ = service_factory()
        # Service requests limit=10001 to detect overflow; mock returns 10001.
        pg.list_records.return_value = [_record(f"r{i}") for i in range(10_001)]
        with pytest.raises(SnapshotOverflowError, match="exceed"):
            await service.create("agent1")
        pg.save_snapshot.assert_not_awaited()

    async def test_emits_snapshot_created_event(self, service_factory) -> None:
        bus = AsyncMock()
        service, pg, _ = service_factory()
        # Inject the bus after construction for terseness.
        service._event_bus = bus
        pg.list_records.return_value = [_record("r1")]

        snapshot = await service.create("agent1")

        bus.emit.assert_awaited_once()
        event_name, payload = bus.emit.await_args.args
        assert event_name == "memory_snapshot_created"
        assert payload == {
            "workspace_id": "ws1",
            "agent_id": "agent1",
            "snapshot_id": snapshot.id,
            "trigger": SnapshotTrigger.MANUAL.value,
            "record_count": 1,
        }


# ---------------------------------------------------------------------------
# get / list
# ---------------------------------------------------------------------------


class TestGetList:
    async def test_get_404(self, service_factory) -> None:
        service, pg, _ = service_factory()
        pg.get_snapshot.return_value = None

        with pytest.raises(MemoryNotFoundError):
            await service.get("missing-id")

    async def test_get_workspace_scoped(self, service_factory) -> None:
        service, pg, _ = service_factory(workspace_id="ws1")
        pg.get_snapshot.return_value = None

        with pytest.raises(MemoryNotFoundError):
            await service.get("snap-from-other-ws")

        # PG store was queried with the bound workspace id (cross-ws lookup
        # is the PG store's responsibility, but we assert the service passes
        # the right workspace).
        pg.get_snapshot.assert_awaited_once_with("ws1", "snap-from-other-ws")

    async def test_list_delegates_to_pg(self, service_factory) -> None:
        service, pg, _ = service_factory()
        pg.list_snapshots.return_value = []
        await service.list_snapshots("agent1")
        pg.list_snapshots.assert_awaited_once_with("ws1", "agent1")


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


class TestRestore:
    async def test_round_trip(self, service_factory) -> None:
        service, pg, qdrant = service_factory()
        records = [_record("r1"), _record("r2")]
        pg.list_records.return_value = records

        snapshot = await service.create("agent1", label="initial")

        # Reset pg fixture to act as the read-back target for restore.
        pg.list_records.return_value = []  # no records before restore (state was reset)
        pg.get_snapshot.return_value = snapshot

        pre_restore, restored = await service.restore(snapshot.id)

        assert restored == 2
        assert pre_restore.trigger == SnapshotTrigger.PRE_RESTORE.value
        # PG.replace_for_agent was called with the original record list.
        pg.replace_for_agent.assert_awaited()
        ws, ag, recs = pg.replace_for_agent.await_args.args
        assert ws == "ws1"
        assert ag == "agent1"
        assert sorted(r.id for r in recs) == ["r1", "r2"]
        # Qdrant upsert called per restored record.
        assert qdrant.upsert.await_count == 2

    async def test_404_when_snapshot_missing(self, service_factory) -> None:
        service, pg, _ = service_factory()
        pg.get_snapshot.return_value = None

        with pytest.raises(MemoryNotFoundError):
            await service.restore("missing")

    async def test_rejects_tampered_file(self, service_factory, tmp_path: Path) -> None:
        service, pg, _ = service_factory()
        pg.list_records.return_value = [_record("r1")]
        snapshot = await service.create("agent1")
        pg.get_snapshot.return_value = snapshot

        # Flip a byte deep into the gzip body.
        target = tmp_path / snapshot.storage_path
        data = bytearray(target.read_bytes())
        data[-1] ^= 0xFF
        target.write_bytes(bytes(data))

        with pytest.raises(SnapshotCorruptError):
            await service.restore(snapshot.id)

    async def test_rejects_workspace_mismatch_in_manifest(self, service_factory) -> None:
        service, pg, _ = service_factory()
        pg.list_records.return_value = [_record("r1")]
        snapshot = await service.create("agent1")

        # Forge a sibling row that lies about the workspace.
        forged = _snapshot_row(
            snapshot_id=snapshot.id,
            agent_id=snapshot.agent_id,
            workspace_id="ws-other",  # mismatch
            storage_path=snapshot.storage_path,
            content_hash=snapshot.content_hash,
            record_count=snapshot.record_count,
        )
        pg.get_snapshot.return_value = forged

        with pytest.raises(SnapshotCorruptError, match="manifest"):
            await service.restore(snapshot.id)

    async def test_replace_value_error_becomes_corrupt(self, service_factory) -> None:
        # If the snapshot file passed checksum + manifest but somehow contains
        # records with foreign workspace/agent (defence in depth), the service
        # surfaces this as a corruption error so the route returns 422.
        service, pg, _ = service_factory()
        pg.list_records.return_value = [_record("r1")]
        snapshot = await service.create("agent1")
        pg.get_snapshot.return_value = snapshot
        pg.replace_for_agent.side_effect = ValueError("workspace/agent mismatch")

        with pytest.raises(SnapshotCorruptError, match="mismatched"):
            await service.restore(snapshot.id)

    async def test_emits_memory_restored_event(self, service_factory) -> None:
        bus = AsyncMock()
        service, pg, _ = service_factory()
        service._event_bus = bus
        pg.list_records.return_value = [_record("r1"), _record("r2")]
        snapshot = await service.create("agent1")
        pg.get_snapshot.return_value = snapshot
        pg.replace_for_agent.side_effect = lambda ws, ag, recs: ([], len(recs))

        bus.emit.reset_mock()
        await service.restore(snapshot.id)

        # Two emits — pre_restore create, then restored.
        events = [call.args[0] for call in bus.emit.await_args_list]
        assert "memory_snapshot_created" in events
        assert "memory_restored" in events
        restored_payload = next(
            call.args[1] for call in bus.emit.await_args_list if call.args[0] == "memory_restored"
        )
        assert set(restored_payload.keys()) == {
            "workspace_id",
            "agent_id",
            "snapshot_id",
            "record_count",
            "pre_restore_snapshot_id",
        }
        assert restored_payload["record_count"] == 2

    async def test_pre_restore_snapshot_recorded(self, service_factory) -> None:
        service, pg, _ = service_factory()
        pg.list_records.return_value = [_record("r1")]
        snapshot = await service.create("agent1")
        pg.get_snapshot.return_value = snapshot
        # After create, list_records is reused; reset it to model 'current'
        # state captured by the pre-restore snapshot.
        pg.list_records.return_value = [_record("current-r")]

        await service.restore(snapshot.id)

        # save_snapshot called twice — initial + pre_restore.
        assert pg.save_snapshot.await_count == 2
        triggers = [call.args[0].trigger for call in pg.save_snapshot.await_args_list]
        assert triggers == [SnapshotTrigger.MANUAL.value, SnapshotTrigger.PRE_RESTORE.value]


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


class TestDiff:
    async def _make_two_snapshots(
        self,
        service_factory,
        from_records: list[MemoryRecord],
        to_records: list[MemoryRecord],
    ) -> tuple[MemorySnapshotService, AsyncMock, MemorySnapshot, MemorySnapshot]:
        service, pg, _ = service_factory()
        pg.list_records.return_value = from_records
        from_snap = await service.create("agent1", label="from")
        pg.list_records.return_value = to_records
        to_snap = await service.create("agent1", label="to")
        # diff() will call get() for both ids — set a mapping side_effect.
        snapshots = {from_snap.id: from_snap, to_snap.id: to_snap}
        pg.get_snapshot.side_effect = lambda ws, sid: snapshots.get(sid)
        return service, pg, from_snap, to_snap

    async def test_added_removed_changed_by_source(self, service_factory) -> None:
        # from: r1(unchanged), r2(will-be-changed), r3(will-be-removed)
        # to:   r1(unchanged), r2_v2(content_hash differs but same source),
        #       r4(added)
        from_records = [
            _record("r1", source_type="conv", source_id="s1", content_hash="h1"),
            _record("r2", source_type="conv", source_id="s2", content_hash="h2"),
            _record("r3", source_type="conv", source_id="s3", content_hash="h3"),
        ]
        to_records = [
            _record("r1", source_type="conv", source_id="s1", content_hash="h1"),
            _record("r2_v2", source_type="conv", source_id="s2", content_hash="h2-changed"),
            _record("r4", source_type="conv", source_id="s4", content_hash="h4"),
        ]
        service, _pg, from_snap, to_snap = await self._make_two_snapshots(
            service_factory, from_records, to_records
        )

        diff = await service.diff(from_snap.id, to_snap.id, key=DiffKey.SOURCE)

        assert diff.added == ["r4"]
        assert diff.removed == ["r3"]
        assert diff.changed == ["r2_v2"]

    async def test_changed_empty_when_keying_by_content_hash(self, service_factory) -> None:
        from_records = [_record("r1", content_hash="h1")]
        to_records = [_record("r2", content_hash="h2")]
        service, _pg, from_snap, to_snap = await self._make_two_snapshots(
            service_factory, from_records, to_records
        )

        diff = await service.diff(from_snap.id, to_snap.id, key=DiffKey.CONTENT_HASH)

        assert diff.added == ["r2"]
        assert diff.removed == ["r1"]
        assert diff.changed == []  # tautological

    async def test_rejects_cross_agent(self, service_factory) -> None:
        service, pg, _ = service_factory()
        pg.list_records.return_value = []
        a1 = await service.create("agent1")
        a2 = await service.create("agent2")
        snapshots = {a1.id: a1, a2.id: a2}
        pg.get_snapshot.side_effect = lambda ws, sid: snapshots.get(sid)

        with pytest.raises(ValueError, match="same-agent"):
            await service.diff(a1.id, a2.id)

    async def test_rejects_same_id(self, service_factory) -> None:
        service, _, _ = service_factory()
        with pytest.raises(ValueError, match="distinct"):
            await service.diff("snap-x", "snap-x")
