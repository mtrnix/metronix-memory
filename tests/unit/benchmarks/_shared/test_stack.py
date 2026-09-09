from __future__ import annotations

import httpx
import respx

from benchmarks._shared import stack

_API = "http://localhost:8000"


@respx.mock
def test_probe_stack_records_health_and_store_status() -> None:
    respx.get(f"{_API}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    respx.get(f"{_API}/api/v1/admin/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "cleanup_allowed": True,
                "databases": {
                    "qdrant": {"status": "connected", "collections_count": 3},
                    "neo4j": {"status": "connected"},
                },
            },
        )
    )

    snapshot = stack.probe_stack(_API + "/")

    assert snapshot == {
        "health": "ok",
        "cleanup_allowed": True,
        "qdrant": "connected",
        "qdrant_collections": 3,
        "neo4j": "connected",
    }


@respx.mock
def test_probe_stack_tolerates_missing_admin_status() -> None:
    respx.get(f"{_API}/health").mock(return_value=httpx.Response(200, text="pong"))
    respx.get(f"{_API}/api/v1/admin/status").mock(return_value=httpx.Response(404))

    snapshot = stack.probe_stack(_API)

    assert snapshot["health"] == 200
    assert snapshot["admin_status"] == 404


@respx.mock
def test_probe_stack_unavailable_on_transport_error() -> None:
    respx.get(f"{_API}/health").mock(side_effect=httpx.ConnectError("refused"))

    snapshot = stack.probe_stack(_API)

    assert snapshot == {"probe": "unavailable", "reason": "ConnectError"}


@respx.mock
def test_reset_workspace_confirms_and_reports_reset() -> None:
    route = respx.delete(f"{_API}/api/v1/admin/cleanup/workspace/LOCOMO").mock(
        return_value=httpx.Response(200, json={"deleted": True})
    )

    assert stack.reset_workspace(_API, "LOCOMO") == "reset"
    assert route.calls.last.request.headers["X-Confirm-Cleanup"] == "yes"


@respx.mock
def test_reset_workspace_reports_disabled_cleanup() -> None:
    respx.delete(f"{_API}/api/v1/admin/cleanup/workspace/WS").mock(
        return_value=httpx.Response(403, json={"detail": "cleanup disabled"})
    )

    assert stack.reset_workspace(_API, "WS") == (
        "unavailable (ALLOW_CLEANUP not enabled on the server)"
    )


@respx.mock
def test_reset_workspace_reports_unexpected_status() -> None:
    respx.delete(f"{_API}/api/v1/admin/cleanup/workspace/WS").mock(
        return_value=httpx.Response(500)
    )

    assert stack.reset_workspace(_API, "WS") == "unavailable (HTTP 500)"


@respx.mock
def test_reset_workspace_reports_transport_error() -> None:
    respx.delete(f"{_API}/api/v1/admin/cleanup/workspace/WS").mock(
        side_effect=httpx.ConnectTimeout("slow")
    )

    assert stack.reset_workspace(_API, "WS") == "unavailable (ConnectTimeout)"
