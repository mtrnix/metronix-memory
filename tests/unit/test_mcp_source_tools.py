"""Unit tests for the metronix_source_* MCP tools.

All tests patch ``_source_deps.resolve`` to inject a FakeConnStore so no live
PostgreSQL is needed.
"""

import asyncio

from metronix.mcp.tools import (
    _source_deps,
    source_create,
    source_delete,
    source_list,
    source_schemas,
    source_sync,
    source_update,
)


class FakeConnStore:
    """In-memory stand-in for PostgresStore connection methods."""

    def __init__(self, connections=None):
        # connections: dict[id] -> connection dict (as get_connection returns)
        self.connections = connections or {}
        self.deleted = []
        self.status_updates = []
        self.sync_logs = []
        self.sync_log_updates = []
        self.created = []
        # Whether a 'syncing' lock has a 'running' sync_logs row behind it
        # (#401/#425). No time window — see postgres.has_running_sync's
        # docstring. Tests flip this to False to exercise the
        # no-running-row reclaim path (release_unstarted_sync_claim).
        self.running_sync = True

    async def list_connections(self, workspace_id, fernet_key):
        return [c for c in self.connections.values() if c["workspace_id"] == workspace_id]

    async def get_connection(self, connection_id, fernet_key):
        return self.connections.get(connection_id)

    async def get_connection_decrypted(self, connection_id, fernet_key):
        return self.connections.get(connection_id)

    async def create_connection(self, *, workspace_id, connector_type, name, config, fernet_key):
        cid = f"conn-{len(self.created) + 1}"
        row = {
            "id": cid,
            "workspace_id": workspace_id,
            "connector_type": connector_type,
            "name": name,
            "config": {"api_token": "***wxyz"},
            "status": "active",
            "enabled": True,
            "error_message": None,
            "last_synced_at": None,
            "created_at": "2026-06-22T00:00:00",
            "updated_at": None,
            "sync_cron": "0 3 * * *",
            "next_run_at": None,
        }
        self.created.append(row)
        self.connections[cid] = row
        return row

    async def update_connection(self, connection_id, updates, fernet_key):
        row = self.connections.get(connection_id)
        if row is None:
            return None
        row.update({k: v for k, v in updates.items() if k in ("name", "enabled")})
        return row

    async def delete_connection(self, connection_id):
        self.deleted.append(connection_id)
        return self.connections.pop(connection_id, None) is not None

    async def claim_connection_for_sync(self, connection_id, claim_id):
        """Faithful atomic claim: wins iff the row isn't already 'syncing'."""
        row = self.connections.get(connection_id)
        if row is None or row.get("status") == "syncing" or not row.get("enabled", True):
            return False
        row["status"] = "syncing"
        row["sync_claim_id"] = claim_id
        self.status_updates.append((connection_id, "syncing"))
        return True

    async def release_sync_claim(self, connection_id, claim_id, error_message):
        """Faithful token-conditioned release: no-op unless claim_id owns it."""
        row = self.connections.get(connection_id)
        if row is None or row.get("sync_claim_id") != claim_id:
            return False
        row["status"] = "error"
        row["sync_claim_id"] = None
        self.status_updates.append((connection_id, "error"))
        return True

    async def update_connection_status(self, connection_id, status, **kwargs):
        self.status_updates.append((connection_id, status))
        if kwargs.get("clear_sync_claim"):
            row = self.connections.get(connection_id)
            if row is not None:
                row["sync_claim_id"] = None

    async def create_sync_log(self, **kwargs):
        self.sync_logs.append(kwargs)

    async def update_sync_log(self, sync_id, **kwargs):
        self.sync_log_updates.append((sync_id, kwargs))

    async def has_running_sync(self, connection_id):
        return self.running_sync


async def _async_noop(*args, **kwargs):
    return None


def _patch_resolve(monkeypatch, store, ws_id="default"):
    monkeypatch.setattr(_source_deps, "resolve", lambda wid: (wid or ws_id, store, "key"))


def _connector_row(cid="c1", workspace_id="default", connector_type="confluence", **extra):
    row = {
        "id": cid,
        "workspace_id": workspace_id,
        "connector_type": connector_type,
        "name": "My Source",
        "config": {"api_token": "***wxyz"},
        "status": "active",
        "enabled": True,
        "error_message": None,
        "last_synced_at": None,
        "created_at": "2026-06-22T00:00:00",
        "updated_at": None,
        "sync_cron": "0 3 * * *",
        "next_run_at": None,
    }
    row.update(extra)
    return row


# --- metronix_source_schemas ---


async def test_schemas_returns_connectors_only():
    out = await source_schemas.metronix_source_schemas()
    assert "error" not in out
    types = {s["type"] for s in out["schemas"]}
    assert "confluence" in types and "jira" in types and "notion" in types
    assert "telegram" not in types and "discord" not in types and "slack" not in types
    confluence = next(s for s in out["schemas"] if s["type"] == "confluence")
    assert {"name", "label", "type", "required"} <= set(confluence["fields"][0].keys())


# --- metronix_source_list ---


async def test_list_returns_workspace_sources_masked(monkeypatch):
    store = FakeConnStore({"c1": _connector_row(config={"api_token": "***wxyz"})})
    _patch_resolve(monkeypatch, store)

    out = await source_list.metronix_source_list()
    assert "error" not in out
    assert out["count"] == 1
    assert out["sources"][0]["config"]["api_token"] == "***wxyz"
    assert out["sources"][0]["id"] == "c1"


async def test_list_scopes_by_workspace(monkeypatch):
    store = FakeConnStore(
        {
            "c1": _connector_row(cid="c1", workspace_id="default"),
            "c2": _connector_row(cid="c2", workspace_id="other"),
        }
    )
    _patch_resolve(monkeypatch, store)

    out = await source_list.metronix_source_list("default")
    ids = {s["id"] for s in out["sources"]}
    assert ids == {"c1"}


# --- metronix_source_create ---


async def test_create_valid_connector(monkeypatch):
    store = FakeConnStore()
    _patch_resolve(monkeypatch, store)
    monkeypatch.setattr("metronix.connectors.connection_sync.ensure_workspace_exists", _async_noop)

    out = await source_create.metronix_source_create(
        "confluence",
        "Docs",
        {"url": "https://x.atlassian.net", "username": "u", "api_token": "tok"},
    )
    assert "error" not in out
    assert out["connector_type"] == "confluence"
    assert out["sync_cron"] == "0 3 * * *"  # re-fetched from DB row
    assert len(store.created) == 1


async def test_create_google_drive_alias_stores_as_gdrive(monkeypatch):
    store = FakeConnStore()
    _patch_resolve(monkeypatch, store)
    monkeypatch.setattr("metronix.connectors.connection_sync.ensure_workspace_exists", _async_noop)

    out = await source_create.metronix_source_create(
        "google_drive",
        "Team Drive",
        {"credentials_json": "{}"},
    )
    assert "error" not in out
    assert out["connector_type"] == "gdrive"
    # The alias must never reach the store — only the canonical name is
    # persisted, so existing `gdrive` rows and code paths are unaffected.
    assert store.created[0]["connector_type"] == "gdrive"


async def test_create_rejects_channel_type(monkeypatch):
    store = FakeConnStore()
    _patch_resolve(monkeypatch, store)
    monkeypatch.setattr("metronix.connectors.connection_sync.ensure_workspace_exists", _async_noop)

    out = await source_create.metronix_source_create("telegram", "Bot", {"bot_token": "t"})
    assert "error" in out
    assert "channel" in out["error"]["message"].lower()
    assert store.created == []


async def test_create_rejects_unknown_type(monkeypatch):
    store = FakeConnStore()
    _patch_resolve(monkeypatch, store)

    out = await source_create.metronix_source_create("sap", "X", {})
    assert "error" in out
    assert store.created == []


async def test_create_missing_required_field(monkeypatch):
    store = FakeConnStore()
    _patch_resolve(monkeypatch, store)
    monkeypatch.setattr("metronix.connectors.connection_sync.ensure_workspace_exists", _async_noop)

    out = await source_create.metronix_source_create("confluence", "Docs", {"url": "https://x"})
    assert "error" in out
    assert store.created == []


# --- metronix_source_update ---


async def test_update_name_and_enabled(monkeypatch):
    store = FakeConnStore({"c1": _connector_row()})
    _patch_resolve(monkeypatch, store)

    out = await source_update.metronix_source_update("c1", name="Renamed", enabled=False)
    assert "error" not in out
    assert out["name"] == "Renamed"
    assert out["enabled"] is False


async def test_update_config_passes_through_without_premerge(monkeypatch):
    store = FakeConnStore({"c1": _connector_row()})
    _patch_resolve(monkeypatch, store)
    captured = {}

    async def _spy_update(connection_id, updates, fernet_key):
        captured["updates"] = updates
        return store.connections[connection_id]

    monkeypatch.setattr(store, "update_connection", _spy_update)

    out = await source_update.metronix_source_update(
        "c1",
        config={"url": "https://x.atlassian.net", "username": "u", "api_token": "***wxyz"},
    )
    assert "error" not in out
    # Tool must NOT pre-merge: it passes config straight through; store merges.
    assert captured["updates"]["config"]["api_token"] == "***wxyz"


async def test_update_cross_workspace_not_found(monkeypatch):
    store = FakeConnStore({"c1": _connector_row(workspace_id="other")})
    _patch_resolve(monkeypatch, store, ws_id="default")

    out = await source_update.metronix_source_update("c1", name="X")
    assert "error" in out
    assert "not found" in out["error"]["message"].lower()


async def test_update_no_fields(monkeypatch):
    store = FakeConnStore({"c1": _connector_row()})
    _patch_resolve(monkeypatch, store)

    out = await source_update.metronix_source_update("c1")
    assert "error" in out


# --- metronix_source_delete ---


async def test_delete_removes_connection(monkeypatch):
    store = FakeConnStore({"c1": _connector_row()})
    _patch_resolve(monkeypatch, store)

    out = await source_delete.metronix_source_delete("c1")
    assert "error" not in out
    assert out["success"] is True
    assert "c1" in store.deleted


async def test_delete_cross_workspace_not_found(monkeypatch):
    store = FakeConnStore({"c1": _connector_row(workspace_id="other")})
    _patch_resolve(monkeypatch, store, ws_id="default")

    out = await source_delete.metronix_source_delete("c1")
    assert "error" in out
    assert "not found" in out["error"]["message"].lower()
    assert store.deleted == []


# --- metronix_source_sync ---


async def test_sync_starts_background_task(monkeypatch):
    store = FakeConnStore({"c1": _connector_row()})
    _patch_resolve(monkeypatch, store)
    ran = {}

    async def _fake_run(**kwargs):
        ran["kwargs"] = kwargs

    monkeypatch.setattr("metronix.connectors.connection_sync.run_connection_sync", _fake_run)

    sentinel_bus = object()
    monkeypatch.setattr("metronix.mcp.server.get_activity_bus", lambda: sentinel_bus)

    out = await source_sync.metronix_source_sync("c1")
    assert "error" not in out
    assert out["status"] == "sync_started"
    assert out["sync_id"].startswith("sync_")
    assert ("c1", "syncing") in store.status_updates
    # Let the scheduled task run.
    await asyncio.sleep(0)
    assert ran["kwargs"]["connection_id"] == "c1"
    # The EventBus must be wired (so SYNC_COMPLETED fires), not None.
    assert ran["kwargs"]["event_bus"] is sentinel_bus


async def test_sync_rejects_when_already_syncing(monkeypatch):
    """#425 review: this must hold no matter how long the running row has
    been running — has_running_sync takes no age parameter at all, so there
    is nothing here that could single out an "old" run for reclaim."""
    store = FakeConnStore({"c1": _connector_row(status="syncing")})
    store.running_sync = True  # lock is backed by a live run, any age
    _patch_resolve(monkeypatch, store)

    out = await source_sync.metronix_source_sync("c1")
    assert "error" in out
    assert "in progress" in out["error"]["message"].lower()


async def test_sync_releases_claim_when_spawn_fails(monkeypatch):
    """#425: a step AFTER 'syncing' is set but BEFORE the background task is
    scheduled raises (here: the connection row has no "config" key, so
    building the run_connection_sync call KeyErrors). The connection lock and
    the pre-inserted 'running' sync_logs row must both reach a terminal state
    via release_unstarted_sync_claim — otherwise has_running_sync() reports
    this connection busy forever, since nothing else can ever reclaim it
    without an actual running row (#401)."""
    row = {
        "id": "c1",
        "workspace_id": "default",
        "connector_type": "confluence",
        "status": "active",
        "enabled": True,
        "last_synced_at": None,
        # No "config" key — metronix_source_sync's
        # run_connection_sync(..., config=conn["config"], ...) KeyErrors
        # while building the call, before asyncio.create_task ever runs.
    }
    store = FakeConnStore({"c1": row})
    store.running_sync = False
    _patch_resolve(monkeypatch, store)

    out = await source_sync.metronix_source_sync("c1")

    assert "error" in out
    # The claim was taken (status set to "syncing" first)...
    assert store.status_updates[0] == ("c1", "syncing")
    # ...then released to a terminal "error" by release_unstarted_sync_claim.
    assert store.status_updates[-1] == ("c1", "error")
    # ...and the pre-inserted sync_logs row was finalized as "failed" too.
    assert store.sync_log_updates
    _, update_kwargs = store.sync_log_updates[0]
    assert update_kwargs["status"] == "failed"


class _RaisingCreateLogStore(FakeConnStore):
    """create_sync_log always raises — a transient DB error on the pre-insert
    INSERT (#425 round 2). It is deliberately non-fatal: the sync must still
    be spawned, with no 'running' sync_logs row behind connections.status
    ending up 'syncing'."""

    async def create_sync_log(self, **kwargs):
        self.sync_logs.append(kwargs)  # record the attempt for assertions
        raise RuntimeError("simulated transient DB error on sync_logs INSERT")


async def test_sync_second_request_blocked_when_create_sync_log_failed(monkeypatch):
    """#425 round 2 review: create_sync_log failing must not let a second,
    concurrent metronix_source_sync call slip past the duplicate-sync guard.

    The guard used to treat has_running_sync()==False as permission to
    proceed even when connections.status=='syncing' — which is exactly the
    state a task left behind when its own create_sync_log INSERT failed. It
    now gates on connections.status alone, so this must be rejected
    regardless of what has_running_sync reports.
    """
    store = _RaisingCreateLogStore({"c1": _connector_row()})
    store.running_sync = False  # no sync_logs row exists — the INSERT failed
    _patch_resolve(monkeypatch, store)

    ran: dict[str, object] = {}

    async def _fake_run(**kwargs):
        ran["kwargs"] = kwargs

    monkeypatch.setattr("metronix.connectors.connection_sync.run_connection_sync", _fake_run)

    # First request: create_sync_log raises, but the sync must still start —
    # that non-fatal behavior is what this test protects, not just the guard.
    out1 = await source_sync.metronix_source_sync("c1")
    assert "error" not in out1
    assert out1["status"] == "sync_started"
    assert store.sync_logs  # create_sync_log was attempted (and raised)
    assert ("c1", "syncing") in store.status_updates
    # The claim was NOT released — the task really is in flight, unlike the
    # spawn-failure test above.
    assert ("c1", "error") not in store.status_updates
    await asyncio.sleep(0)
    assert ran["kwargs"]["connection_id"] == "c1"

    # The first claim mutated the row to 'syncing'. A second, concurrent
    # request must lose the atomic claim — even though has_running_sync
    # (store.running_sync) is False.
    assert store.connections["c1"]["status"] == "syncing"
    out2 = await source_sync.metronix_source_sync("c1")
    assert "error" in out2
    assert "in progress" in out2["error"]["message"].lower()


async def test_sync_race_loser_cannot_clobber_the_live_claim(monkeypatch):
    """#425: two overlapping metronix_source_sync calls. The atomic claim lets
    exactly one win and spawn a live sync; the loser gets rejected and never
    reaches a release path, so it cannot drop the connection out of 'syncing'
    and let a third call start concurrently."""
    store = FakeConnStore({"c1": _connector_row()})
    store.running_sync = True
    _patch_resolve(monkeypatch, store)

    async def _fake_run(**kwargs):
        pass

    monkeypatch.setattr("metronix.connectors.connection_sync.run_connection_sync", _fake_run)
    monkeypatch.setattr("metronix.mcp.server.get_activity_bus", lambda: object())

    out_a = await source_sync.metronix_source_sync("c1")
    out_b = await source_sync.metronix_source_sync("c1")

    assert out_a["status"] == "sync_started"
    assert "error" in out_b and "in progress" in out_b["error"]["message"].lower()
    # The loser released nothing — the winner's lock/token survive.
    assert ("c1", "error") not in store.status_updates
    assert store.connections["c1"]["status"] == "syncing"
    assert store.connections["c1"]["sync_claim_id"] == out_a["sync_id"]

    out_c = await source_sync.metronix_source_sync("c1")
    assert "error" in out_c and "in progress" in out_c["error"]["message"].lower()


async def test_sync_rejects_scaffold_connector(monkeypatch):
    # slack_history is still a scaffold (unimplemented) connector; gdrive/github now sync.
    store = FakeConnStore({"c1": _connector_row(connector_type="slack_history")})
    _patch_resolve(monkeypatch, store)

    out = await source_sync.metronix_source_sync("c1")
    assert "error" in out
    assert "not implemented" in out["error"]["message"].lower()


async def test_sync_rejects_disabled(monkeypatch):
    store = FakeConnStore({"c1": _connector_row(enabled=False)})
    _patch_resolve(monkeypatch, store)

    out = await source_sync.metronix_source_sync("c1")
    assert "error" in out
    assert "disabled" in out["error"]["message"].lower()


async def test_sync_rejects_channel(monkeypatch):
    store = FakeConnStore({"c1": _connector_row(connector_type="telegram")})
    _patch_resolve(monkeypatch, store)

    out = await source_sync.metronix_source_sync("c1")
    assert "error" in out
