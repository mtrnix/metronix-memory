import metronix.export.deps as deps
from metronix.core.config import Settings
from metronix.export.deps import build_export_service
from metronix.export.service import ExportService


def test_build_export_service_constructs(monkeypatch, tmp_path):
    monkeypatch.setenv("METRONIX_EXPORT_DIR", str(tmp_path))
    deps._SERVICE = None  # reset module-level cache for a clean test
    svc = build_export_service(Settings())
    assert isinstance(svc, ExportService)
    # cached: same instance on second call
    assert build_export_service(Settings()) is svc
