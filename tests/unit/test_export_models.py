from datetime import UTC, datetime

from metronix.export.models import ExportJob, ExportScope, ExportStatus


def test_scope_roundtrip_and_key():
    s = ExportScope(all_workspaces=False, workspace_id="ws1")
    assert ExportScope.from_dict(s.to_dict()) == s
    assert s.key() == "ws:ws1"
    assert ExportScope(all_workspaces=True).key() == "all"


def test_job_status_enum():
    now = datetime.now(UTC)
    job = ExportJob(
        id="e1",
        scope=ExportScope(workspace_id="ws1"),
        status=ExportStatus.PENDING,
        created_at=now,
        updated_at=now,
    )
    assert job.status == "pending"
