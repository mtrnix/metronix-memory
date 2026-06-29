from metronix.api.routes import connections
from metronix.connectors import connection_sync


def test_route_delegates_to_extracted_sync():
    # The REST route must reference the extracted L3 functions, not private copies.
    assert connections.run_connection_sync is connection_sync.run_connection_sync
    assert connections.ensure_workspace_exists is connection_sync.ensure_workspace_exists


def test_route_uses_extracted_registry_and_sanitizer():
    assert connections.get_registry is connection_sync.get_registry
    assert connections.sanitize_error is connection_sync.sanitize_error


def test_private_helpers_removed_from_route():
    # Old private names must be gone (callers migrated to the L3 module).
    for name in (
        "_run_connection_sync",
        "_ensure_workspace_exists",
        "_get_registry",
        "_sanitize_error",
    ):
        assert not hasattr(connections, name), f"{name} should have moved to connection_sync"
