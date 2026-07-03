from __future__ import annotations

from metronix.client import MetronixClient


class _Response:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


def test_request_appends_workspace_and_bearer_header(monkeypatch):
    seen: dict[str, object] = {}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        seen["method"] = method
        seen["url"] = url
        seen["headers"] = headers
        seen["timeout"] = timeout
        return _Response({"results": []})

    client = MetronixClient(
        base_url="http://localhost:8000",
        workspace_id="MTRNIX",
        auth_token="token-123",
    )
    monkeypatch.setattr(client._session, "request", fake_request)

    client.search_memory(query="hello", top_k=3)

    assert seen["method"] == "POST"
    assert seen["url"] == "http://localhost:8000/api/v1/memory/search?workspace_id=MTRNIX"
    assert seen["headers"]["Authorization"] == "Bearer token-123"


def test_login_fallback_caches_token(monkeypatch):
    login_calls: list[object] = []
    request_calls: list[object] = []

    def fake_post(url, json=None, timeout=None):
        login_calls.append((url, json, timeout))
        return _Response({"token": "jwt-abc"})

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        request_calls.append((method, url, headers, timeout))
        return _Response({"status": "ok"})

    client = MetronixClient(
        base_url="http://localhost:8000",
        workspace_id="MTRNIX",
        email="admin@example.com",
        password="password",
    )
    monkeypatch.setattr(client._session, "post", fake_post)
    monkeypatch.setattr(client._session, "request", fake_request)

    client.ping()
    client.ping()

    assert len(login_calls) == 1
    assert len(request_calls) == 2
    assert request_calls[0][2]["Authorization"] == "Bearer jwt-abc"


def test_request_retries_with_login_on_401(monkeypatch):
    login_calls: list[object] = []
    request_calls: list[object] = []

    def fake_post(url, json=None, timeout=None):
        login_calls.append((url, json, timeout))
        return _Response({"token": "jwt-fresh"})

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        request_calls.append((method, url, headers, timeout))
        if len(request_calls) == 1:
            return _Response({"detail": "unauthorized"}, status_code=401)
        return _Response({"status": "ok"})

    client = MetronixClient(
        base_url="http://localhost:8000",
        workspace_id="MTRNIX",
        auth_token="mcp-token-not-rest-token",
        email="admin@example.com",
        password="password",
    )
    monkeypatch.setattr(client._session, "post", fake_post)
    monkeypatch.setattr(client._session, "request", fake_request)

    payload = client.ping()

    assert payload["status"] == "ok"
    assert len(request_calls) == 2
    assert len(login_calls) == 1
    assert request_calls[0][2]["Authorization"] == "Bearer mcp-token-not-rest-token"
    assert request_calls[1][2]["Authorization"] == "Bearer jwt-fresh"
