"""AgentIdContextMiddleware — populates current_agent_id from X-Agent-Id header."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

if TYPE_CHECKING:
    from starlette.requests import Request

from metronix.activity.context import current_agent_id
from metronix.api.middleware.agent_id import AgentIdContextMiddleware


def _app() -> Starlette:
    async def view(_request: Request) -> JSONResponse:
        return JSONResponse({"agent": current_agent_id.get()})

    return Starlette(
        routes=[Route("/echo", view)],
        middleware=[Middleware(AgentIdContextMiddleware)],
    )


def test_header_sets_context() -> None:
    client = TestClient(_app())
    r = client.get("/echo", headers={"X-Agent-Id": "ag_42"})
    assert r.status_code == 200
    assert r.json() == {"agent": "ag_42"}


def test_no_header_leaves_context_none() -> None:
    client = TestClient(_app())
    r = client.get("/echo")
    assert r.status_code == 200
    assert r.json() == {"agent": None}


def test_invalid_header_ignored_too_long() -> None:
    client = TestClient(_app())
    long_id = "a" * 65
    r = client.get("/echo", headers={"X-Agent-Id": long_id})
    assert r.status_code == 200
    assert r.json() == {"agent": None}


def test_invalid_header_ignored_non_printable() -> None:
    client = TestClient(_app())
    r = client.get("/echo", headers={"X-Agent-Id": "ag\x01x"})
    assert r.status_code == 200
    assert r.json() == {"agent": None}


def test_invalid_header_ignored_path_unsafe() -> None:
    """Chars outside A-Za-z0-9._- (here a slash and a space) are rejected so an
    id that survives the header cannot break the /agents/{id} REST routes."""
    client = TestClient(_app())
    for bad in ("a/b", "ag id"):
        r = client.get("/echo", headers={"X-Agent-Id": bad})
        assert r.status_code == 200
        assert r.json() == {"agent": None}


def test_empty_header_ignored() -> None:
    client = TestClient(_app())
    r = client.get("/echo", headers={"X-Agent-Id": ""})
    assert r.status_code == 200
    assert r.json() == {"agent": None}


def test_context_is_reset_between_requests() -> None:
    client = TestClient(_app())
    r1 = client.get("/echo", headers={"X-Agent-Id": "first"})
    r2 = client.get("/echo")  # no header
    assert r1.json() == {"agent": "first"}
    assert r2.json() == {"agent": None}
