"""Unit tests for connection_sync.release_unstarted_sync_claim (#401/#425).

Shared by every sync entry point (autosync tick, REST trigger_sync,
metronix_source_sync) to undo a claim that never handed off to a running
run_connection_sync task. Tested in isolation here with a fake store; each
call site's own test (test_autosync.py, test_connections_sync.py,
test_mcp_source_tools.py) verifies it is actually invoked on a spawn failure.

The release is ownership-conditioned: it only touches the connection while
sync_claim_id still equals claim_id (store.release_sync_claim returns whether
it matched). A mismatch — another request owns the lock now, or a completed
run / recovery already cleared it, or it is a pre-token orphan — is a no-op on
the connection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from metronix.connectors.connection_sync import release_unstarted_sync_claim


class _FakeStore:
    def __init__(self, *, released: bool = True) -> None:
        # release_sync_claim(connection_id, claim_id, message) -> bool
        self.release_sync_claim = AsyncMock(return_value=released)
        self.update_sync_log = AsyncMock()


async def test_releases_the_claim_and_finalizes_the_log_row() -> None:
    store = _FakeStore(released=True)

    await release_unstarted_sync_claim(
        store, "conn-1", claim_id="sync-1", sync_id="sync-1", message="could not start"
    )

    store.release_sync_claim.assert_awaited_once_with("conn-1", "sync-1", "could not start")
    store.update_sync_log.assert_awaited_once_with(
        "sync-1", status="failed", errors=["could not start"]
    )


async def test_claim_not_ours_leaves_the_connection_untouched() -> None:
    """The token no longer matches (a live sync owns the lock now). The
    connection must not be written — only this attempt's own sync_logs row
    is finalized (#425)."""
    store = _FakeStore(released=False)

    await release_unstarted_sync_claim(
        store, "conn-1", claim_id="sync-mine", sync_id="sync-mine", message="lost the race"
    )

    store.release_sync_claim.assert_awaited_once()
    # The log row is still ours to close out.
    store.update_sync_log.assert_awaited_once_with(
        "sync-mine", status="failed", errors=["lost the race"]
    )


async def test_skips_the_log_write_when_no_row_was_ever_created() -> None:
    """create_sync_log can fail before a claim is released (non-fatal at the
    call site) — sync_id is then None and there is no row to finalize."""
    store = _FakeStore()

    await release_unstarted_sync_claim(
        store, "conn-1", claim_id="sync-1", sync_id=None, message="could not start"
    )

    store.release_sync_claim.assert_awaited_once()
    store.update_sync_log.assert_not_awaited()


async def test_connection_release_failure_does_not_prevent_the_log_write() -> None:
    """Releasing the claim is itself best-effort — one failing write must not
    stop the other, and neither may raise into the caller's own error path."""
    store = _FakeStore()
    store.release_sync_claim.side_effect = RuntimeError("db down")

    await release_unstarted_sync_claim(
        store, "conn-1", claim_id="sync-1", sync_id="sync-1", message="msg"
    )

    store.update_sync_log.assert_awaited_once()


async def test_log_write_failure_is_swallowed() -> None:
    store = _FakeStore()
    store.update_sync_log.side_effect = RuntimeError("db down")

    # Must not raise.
    await release_unstarted_sync_claim(
        store, "conn-1", claim_id="sync-1", sync_id="sync-1", message="msg"
    )
