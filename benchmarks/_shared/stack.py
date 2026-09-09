"""Best-effort Metronix stack probing and workspace reset for the runners.

Uses ``httpx`` (in the runners' venv). Everything here degrades gracefully — a
probe failure never aborts a benchmark, it just records ``"unavailable"`` in the
manifest so the comparator can see the difference.
"""

from __future__ import annotations

from typing import Any

import httpx

_TIMEOUT = httpx.Timeout(15.0)


def probe_stack(api_url: str) -> dict[str, Any]:
    """A snapshot of what the server will tell us — health + store connectivity.

    The API does not expose the embedding model or the retrieval flags, so those
    stay operator-declared; this records the parts it does expose so a leg run
    with (say) Neo4j down is visibly not comparable to one with it up.
    """
    api_url = api_url.rstrip("/")
    snapshot: dict[str, Any] = {}
    try:
        with httpx.Client(timeout=_TIMEOUT, trust_env=False) as client:
            health = client.get(f"{api_url}/health")
            snapshot["health"] = (
                health.json().get("status", health.status_code)
                if health.headers.get("content-type", "").startswith("application/json")
                else health.status_code
            )
            status = client.get(f"{api_url}/api/v1/admin/status")
            if status.status_code == 200:
                body = status.json()
                dbs = body.get("databases", {})
                snapshot["cleanup_allowed"] = body.get("cleanup_allowed")
                snapshot["qdrant"] = (dbs.get("qdrant") or {}).get("status")
                snapshot["qdrant_collections"] = (dbs.get("qdrant") or {}).get("collections_count")
                snapshot["neo4j"] = (dbs.get("neo4j") or {}).get("status")
            else:
                snapshot["admin_status"] = status.status_code
    except (httpx.HTTPError, ValueError) as exc:
        return {"probe": "unavailable", "reason": type(exc).__name__}
    return snapshot


def reset_workspace(api_url: str, workspace_id: str) -> str:
    """DELETE all data for ``workspace_id``. Returns a short status string.

    Needs ``ALLOW_CLEANUP=true`` on the server. Any failure is reported, not
    raised — the caller records the string in the manifest.
    """
    api_url = api_url.rstrip("/")
    try:
        with httpx.Client(timeout=_TIMEOUT, trust_env=False) as client:
            response = client.request(
                "DELETE",
                f"{api_url}/api/v1/admin/cleanup/workspace/{workspace_id}",
                headers={"X-Confirm-Cleanup": "yes"},
            )
    except httpx.HTTPError as exc:
        return f"unavailable ({type(exc).__name__})"
    if response.status_code == 200:
        return "reset"
    if response.status_code in (400, 403):
        return "unavailable (ALLOW_CLEANUP not enabled on the server)"
    return f"unavailable (HTTP {response.status_code})"
