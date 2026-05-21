"""
Zone: health
Endpoints covered: GET /health, GET /ready, GET /metrics
Last actualized: 2026-05-21
"""
import pytest
import httpx

API = "http://drp-m.mtrnix.com:8000"
TIMEOUT = 30


class TestGetHealth:
    """GET /health — 4 scenarios (1 positive, 1 negative, 1 edge, 1 security)."""

    # type: positive, checks: [functional]
    def test_health_returns_200(self):
        """Happy path: basic health endpoint returns 200."""
        r = httpx.get(f"{API}/health", timeout=TIMEOUT)
        assert r.status_code == 200

    # type: negative
    def test_health_wrong_method_returns_405(self):
        """POST to /health → 405 Method Not Allowed."""
        r = httpx.post(f"{API}/health", timeout=TIMEOUT)
        assert r.status_code == 405

    # type: edge
    def test_health_accepts_no_auth(self):
        """Health endpoint is public — no token, no 401."""
        r = httpx.get(f"{API}/health", timeout=TIMEOUT)
        assert r.status_code == 200
        # Ensure no auth-related headers in response
        assert "www-authenticate" not in r.headers.get("www-authenticate", "").lower()

    # type: edge, checks: [performance]
    def test_health_response_under_500ms(self):
        """Health responds within 500ms."""
        import time
        start = time.monotonic()
        r = httpx.get(f"{API}/health", timeout=TIMEOUT)
        elapsed = time.monotonic() - start
        assert r.status_code == 200
        assert elapsed < 0.5, f"Health took {elapsed:.2f}s, expected < 0.5s"


class TestGetReady:
    """GET /ready — 4 scenarios (1 positive, 2 negative, 1 edge)."""

    # type: positive, checks: [functional]
    def test_ready_returns_200_with_services(self):
        """Happy path: /ready returns 200 with service status."""
        r = httpx.get(f"{API}/ready", timeout=TIMEOUT)
        assert r.status_code == 200
        body = r.json()
        assert "status" in body
        assert "services" in body
        assert body["status"] == "ready"

    # type: negative
    def test_ready_wrong_method_returns_405(self):
        """PUT to /ready → 405."""
        r = httpx.put(f"{API}/ready", timeout=TIMEOUT)
        assert r.status_code == 405

    # type: negative
    def test_ready_delete_returns_405(self):
        """DELETE to /ready → 405."""
        r = httpx.delete(f"{API}/ready", timeout=TIMEOUT)
        assert r.status_code == 405

    # type: edge
    def test_ready_accepts_no_auth(self):
        """Ready endpoint is public — no auth required."""
        r = httpx.get(f"{API}/ready", timeout=TIMEOUT)
        assert r.status_code == 200


class TestGetMetrics:
    """GET /metrics — 4 scenarios (1 positive, 1 negative, 2 edges)."""

    # type: positive, checks: [functional]
    def test_metrics_returns_200(self):
        """Happy path: /metrics returns 200."""
        r = httpx.get(f"{API}/metrics", timeout=TIMEOUT)
        assert r.status_code == 200

    # type: positive, checks: [functional]
    def test_metrics_has_uptime(self):
        """Metrics body contains uptime_sec field."""
        r = httpx.get(f"{API}/metrics", timeout=TIMEOUT)
        body = r.json()
        assert "uptime_sec" in body
        assert isinstance(body["uptime_sec"], (int, float))
        assert body["uptime_sec"] > 0

    # type: negative
    def test_metrics_wrong_method_returns_405(self):
        """PATCH to /metrics → 405."""
        r = httpx.patch(f"{API}/metrics", timeout=TIMEOUT)
        assert r.status_code == 405

    # type: edge, checks: [security]
    def test_metrics_does_not_leak_sensitive_info(self):
        """Metrics should not expose secrets or paths."""
        r = httpx.get(f"{API}/metrics", timeout=TIMEOUT)
        body_text = r.text.lower()
        assert "password" not in body_text
        assert "secret" not in body_text
        assert "api_key" not in body_text
