import time
import zipfile

import pytest
from starlette.testclient import TestClient

from metronix.api.app import create_app
from metronix.api.dependencies import resolve_workspace_id

pytestmark = pytest.mark.integration


def test_export_e2e_zip_downloadable(tmp_path, monkeypatch):
    monkeypatch.setenv("METRONIX_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("METRONIX_PUBLIC_BASE_URL", "http://testserver")
    app = create_app()
    app.dependency_overrides[resolve_workspace_id] = lambda: "ws_e2e"

    # The status route authorizes against request.state.user; stamp an admin user
    # so the export-scope access check passes (real deployments use auth middleware).
    @app.middleware("http")
    async def _fake_user(request, call_next):
        request.state.user = {"workspace_ids": ["*"]}
        return await call_next(request)

    with TestClient(app) as client:
        started = client.post("/api/v1/export", json={"workspace_id": "ws_e2e"})
        assert started.status_code == 200
        export_id = started.json()["export_id"]

        # poll until ready
        url = None
        for _ in range(50):
            st = client.get(f"/api/v1/export/{export_id}").json()
            if st["status"] == "ready":
                url = st["download_url"]
                break
            if st["status"] == "failed":
                pytest.fail(f"export failed: {st.get('error')}")
            time.sleep(0.2)
        assert url is not None, "export did not become ready"

        # download via the one-time URL (strip host -> path+query for TestClient)
        path_q = url.split("testserver", 1)[1]
        dl = client.get(path_q)
        assert dl.status_code == 200
        assert dl.headers["content-type"] == "application/zip"
        zip_path = tmp_path / "downloaded.zip"
        zip_path.write_bytes(dl.content)
        with zipfile.ZipFile(zip_path) as z:
            assert "manifest.json" in z.namelist()

        # token is one-time: second download fails
        again = client.get(path_q)
        assert again.status_code == 404
