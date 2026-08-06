import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from metronix.connectors.gdrive import GDriveConnector
from metronix.connectors.gdrive_processing import FOLDER_MIME
from metronix.core.models import Connection

SA_JSON = '{"type": "service_account", "project_id": "p"}'


def test_source_role_is_knowledge_base():
    assert GDriveConnector.source_role == "knowledge_base"


def test_build_credentials_service_account():
    connector = GDriveConnector()
    with patch("google.oauth2.service_account.Credentials") as sa:
        connector._build_credentials({"credentials_json": SA_JSON})
        sa.from_service_account_info.assert_called_once()


def test_build_credentials_raises_without_json():
    connector = GDriveConnector()
    with pytest.raises(ValueError, match="Service Account JSON"):
        connector._build_credentials({"folder_id": "f"})


def test_configure_builds_service():
    connector = GDriveConnector()
    conn = Connection(id="c1", workspace_id="ws1", connector_type="gdrive")
    with (
        patch.object(GDriveConnector, "_build_credentials", return_value=MagicMock()),
        patch("googleapiclient.discovery.build") as build,
    ):
        asyncio.run(connector.configure(conn, {"credentials_json": SA_JSON}))
        build.assert_called_once()
        assert connector._service is build.return_value


def test_health_check_false_when_not_configured():
    assert asyncio.run(GDriveConnector().health_check()) is False


def test_health_check_true_on_success():
    connector = GDriveConnector()
    connector._service = MagicMock()
    connector._config = {}
    assert asyncio.run(connector.health_check()) is True
    connector._service.files.return_value.list.assert_called()


def test_health_check_false_on_exception():
    connector = GDriveConnector()
    connector._service = MagicMock()
    connector._config = {}
    connector._service.files.return_value.list.side_effect = Exception("bad creds")
    assert asyncio.run(connector.health_check()) is False


def test_health_check_scopes_to_shared_drive():
    connector = GDriveConnector()
    connector._service = MagicMock()
    connector._config = {"shared_drive_id": "D1"}
    asyncio.run(connector.health_check())
    _, kwargs = connector._service.files.return_value.list.call_args
    assert kwargs["driveId"] == "D1"
    assert kwargs["corpora"] == "drive"


def test_health_check_scopes_to_folder():
    connector = GDriveConnector()
    connector._service = MagicMock()
    connector._config = {"folder_id": "FID"}
    asyncio.run(connector.health_check())
    _, kwargs = connector._service.files.return_value.list.call_args
    assert "'FID' in parents" in kwargs["q"]
    assert "corpora" not in kwargs


def test_health_check_no_scope_probes_shared_with_me():
    connector = GDriveConnector()
    connector._service = MagicMock()
    connector._config = {}
    asyncio.run(connector.health_check())
    _, kwargs = connector._service.files.return_value.list.call_args
    assert "sharedWithMe = true" in kwargs["q"]


def test_health_check_folder_in_shared_drive_matches_sync_scope():
    # Both set → probe the folder (sync's priority), drive-scoped like _walk_folder.
    connector = GDriveConnector()
    connector._service = MagicMock()
    connector._config = {"folder_id": "FID", "shared_drive_id": "D1"}
    asyncio.run(connector.health_check())
    _, kwargs = connector._service.files.return_value.list.call_args
    assert "'FID' in parents" in kwargs["q"]
    assert kwargs["driveId"] == "D1"
    assert kwargs["corpora"] == "drive"


def test_configure_rejects_malformed_folder_id():
    connector = GDriveConnector()
    conn = Connection(id="c1", workspace_id="ws1", connector_type="gdrive")
    bad = {"credentials_json": SA_JSON, "folder_id": "a' or x"}
    with pytest.raises(ValueError, match="invalid folder_id"):
        asyncio.run(connector.configure(conn, bad))


def test_configure_accepts_valid_ids():
    connector = GDriveConnector()
    conn = Connection(id="c1", workspace_id="ws1", connector_type="gdrive")
    with (
        patch.object(GDriveConnector, "_build_credentials", return_value=MagicMock()),
        patch("googleapiclient.discovery.build"),
    ):
        cfg = {
            "credentials_json": SA_JSON,
            "folder_id": "1AbC_9-xyz",
            "shared_drive_id": "0AK-9z",
        }
        asyncio.run(connector.configure(conn, cfg))
        assert connector._service is not None


def _doc_meta(mime, name="f", size=None):
    m = {"id": "X1", "name": name, "mimeType": mime, "modifiedTime": "2026-06-01T00:00:00Z"}
    if size is not None:
        m["size"] = size
    return m


def test_process_file_exports_google_doc():
    connector = GDriveConnector()
    connector._service = MagicMock()
    connector._service.files.return_value.export_media.return_value.execute.return_value = (
        b"# hello"
    )
    doc = connector._process_file(_doc_meta("application/vnd.google-apps.document", "Doc"), "ws1")
    assert doc is not None
    assert doc.content == "# hello"
    _, kwargs = connector._service.files.return_value.export_media.call_args
    assert kwargs["mimeType"] == "text/markdown"
    assert kwargs["fileId"] == "X1"


def test_process_file_downloads_binary_via_parse_upload():
    connector = GDriveConnector()
    connector._service = MagicMock()
    connector._service.files.return_value.get_media.return_value.execute.return_value = (
        b"%PDF-1.4 ..."
    )
    with patch("metronix.connectors.gdrive.parse_upload", return_value="pdf text") as pu:
        doc = connector._process_file(
            _doc_meta("application/pdf", "report.pdf", size="500"), "ws1"
        )
        assert doc is not None
        assert doc.content == "pdf text"
        pu.assert_called_once()


def test_process_file_skips_oversized_binary():
    connector = GDriveConnector()
    connector._service = MagicMock()
    doc = connector._process_file(
        _doc_meta("application/pdf", "big.pdf", size=str(2_000_000)), "ws1"
    )
    assert doc is None
    connector._service.files.return_value.get_media.assert_not_called()


def test_process_file_skips_unsupported_mime():
    connector = GDriveConnector()
    connector._service = MagicMock()
    doc = connector._process_file(_doc_meta("image/png", "pic.png"), "ws1")
    assert doc is None


def _fake_list(pages):
    """Build a service whose files().list(...).execute() returns queued pages.

    Records every `q` passed to list() in `service._queries`.
    """
    service = MagicMock()
    service._queries = []
    calls = {"n": 0}

    def _list(**kwargs):
        service._queries.append(kwargs.get("q", ""))
        req = MagicMock()
        idx = calls["n"]
        calls["n"] += 1
        req.execute.return_value = pages[idx] if idx < len(pages) else {"files": []}
        return req

    service.files.return_value.list.side_effect = _list
    # Every fetch now captures a fresh start page token during the full sweep.
    service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
        "startPageToken": "T-START",
    }
    return service


def test_load_and_take_cursor_roundtrip():
    c = GDriveConnector()
    assert c.take_cursor() is None
    c.load_cursor("PT")
    assert c._resume_cursor == "PT"


def test_full_sweep_captures_start_page_token():
    connector = GDriveConnector()
    connector._config = {}
    connector._service = _fake_list(
        [
            {
                "files": [
                    {
                        "id": "A",
                        "name": "a.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-06-10T00:00:00Z",
                        "size": "2",
                    },
                ]
            }
        ]
    )
    connector._service.files.return_value.get_media.return_value.execute.return_value = b"x"
    with patch("metronix.connectors.gdrive.parse_upload", return_value="x"):
        docs = asyncio.run(connector.fetch("ws1"))  # since=None → full sweep
    assert [d.source_id for d in docs] == ["A"]
    assert connector.take_cursor() == "T-START"


def test_fields_include_trashed():
    from metronix.connectors.gdrive import _FIELDS

    assert "trashed" in _FIELDS


def test_fetch_raises_when_not_configured():
    with pytest.raises(RuntimeError):
        asyncio.run(GDriveConnector().fetch("ws1"))


def test_fetch_no_scope_uses_shared_with_me():
    """Empty folder_id/shared_drive_id → index everything shared with the SA,
    discovered via `sharedWithMe = true` (a bare list would miss shared items)."""
    connector = GDriveConnector()
    connector._config = {}
    connector._service = _fake_list(
        [
            {
                "files": [
                    {
                        "id": "A",
                        "name": "a.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-06-10T00:00:00Z",
                        "size": "5",
                    },
                ]
            }
        ]
    )
    connector._service.files.return_value.get_media.return_value.execute.return_value = b"hi"
    with patch("metronix.connectors.gdrive.parse_upload", return_value="hi"):
        docs = asyncio.run(connector.fetch("ws1"))
    assert [d.source_id for d in docs] == ["A"]
    q = connector._service._queries[0]
    assert "trashed = false" in q
    assert "sharedWithMe = true" in q


def test_fetch_no_scope_walks_shared_folders():
    """Full sweep (no scope): sharedWithMe roots — a shared folder is traversed
    for its contents, a loose shared file is taken directly; all returned."""
    connector = GDriveConnector()
    connector._config = {}
    connector._service = _fake_list(
        [
            # Page 1: sharedWithMe roots — one folder + one loose file.
            {
                "files": [
                    {"id": "SF", "name": "shared", "mimeType": FOLDER_MIME},
                    {
                        "id": "LOOSE",
                        "name": "loose.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-06-20T00:00:00Z",
                        "size": "4",
                    },
                ]
            },
            # Page 2: children of SF — two files.
            {
                "files": [
                    {
                        "id": "IN",
                        "name": "in.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-06-21T00:00:00Z",
                        "size": "4",
                    },
                    {
                        "id": "OLD",
                        "name": "old.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-01-02T00:00:00Z",
                        "size": "4",
                    },
                ]
            },
        ]
    )
    connector._service.files.return_value.get_media.return_value.execute.return_value = b"x"
    with patch("metronix.connectors.gdrive.parse_upload", return_value="x"):
        docs = asyncio.run(connector.fetch("ws1"))
    assert {d.source_id for d in docs} == {"LOOSE", "IN", "OLD"}  # SF folder not emitted
    assert "sharedWithMe = true" in connector._service._queries[0]
    assert "in parents" in connector._service._queries[1]


def test_fetch_folder_full_sweep_descends_and_returns_all():
    """Full sweep (folder_id) recurses into subfolders and returns every file —
    no modifiedTime filtering (incremental change detection is separate)."""
    connector = GDriveConnector()
    connector._config = {"folder_id": "ROOT"}
    # Page 1: children of ROOT → one subfolder. Page 2: children of SUB → two files.
    connector._service = _fake_list(
        [
            {"files": [{"id": "SUB", "name": "sub", "mimeType": FOLDER_MIME}]},
            {
                "files": [
                    {
                        "id": "F1",
                        "name": "f1.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-06-20T00:00:00Z",
                        "size": "3",
                    },
                    {
                        "id": "F2",
                        "name": "f2.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-01-05T00:00:00Z",
                        "size": "3",
                    },
                ]
            },
        ]
    )
    connector._service.files.return_value.get_media.return_value.execute.return_value = b"x"
    with patch("metronix.connectors.gdrive.parse_upload", return_value="x"):
        docs = asyncio.run(connector.fetch("ws1"))
    assert {d.source_id for d in docs} == {"F1", "F2"}
    for q in connector._service._queries:
        assert "in parents" in q
        assert "modifiedTime >" not in q


def test_fetch_shared_drive_scopes_params():
    connector = GDriveConnector()
    connector._config = {"shared_drive_id": "D1"}
    connector._service = _fake_list([{"files": []}])
    asyncio.run(connector.fetch("ws1"))
    _, kwargs = connector._service.files.return_value.list.call_args
    assert kwargs["driveId"] == "D1"
    assert kwargs["corpora"] == "drive"
    assert kwargs["includeItemsFromAllDrives"] is True
    assert kwargs["supportsAllDrives"] is True


def test_fetch_isolates_per_file_errors():
    connector = GDriveConnector()
    connector._config = {}
    connector._service = _fake_list(
        [
            {
                "files": [
                    {
                        "id": "OK",
                        "name": "ok.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-06-10T00:00:00Z",
                        "size": "2",
                    },
                    {
                        "id": "BAD",
                        "name": "bad.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-06-10T00:00:00Z",
                        "size": "2",
                    },
                ]
            }
        ]
    )

    def _parse(name, data):
        if name == "bad.txt":
            raise ValueError("boom")
        return "ok"

    connector._service.files.return_value.get_media.return_value.execute.return_value = b"x"
    with patch("metronix.connectors.gdrive.parse_upload", side_effect=_parse):
        docs = asyncio.run(connector.fetch("ws1"))
    assert [d.source_id for d in docs] == ["OK"]


def _fake_changes(pages, service=None):
    """Attach a changes().list side-effect returning queued pages.

    Each page: {"changes": [...], "nextPageToken": ...|None, "newStartPageToken": ...}.
    """
    service = service or MagicMock()
    calls = {"n": 0}

    def _list(**kwargs):
        req = MagicMock()
        idx = calls["n"]
        calls["n"] += 1
        req.execute.return_value = pages[idx] if idx < len(pages) else {"changes": []}
        return req

    service.changes.return_value.list.side_effect = _list
    service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
        "startPageToken": "T-START",
    }
    return service


def _change(
    fid,
    name,
    mime="text/plain",
    modified="2025-01-01T00:00:00Z",
    removed=False,
    trashed=False,
    size="3",
    parents=None,
):
    entry = {"removed": removed, "fileId": fid}
    if not removed:
        entry["file"] = {
            "id": fid,
            "name": name,
            "mimeType": mime,
            "modifiedTime": modified,
            "size": size,
            "trashed": trashed,
            "parents": parents or [],
        }
    return entry


def test_incremental_returns_changed_files_and_captures_token():
    connector = GDriveConnector()
    connector._config = {}
    connector.load_cursor("CURSOR0")
    connector._service = _fake_changes(
        [
            {"changes": [_change("A", "a.txt")], "newStartPageToken": "T-NEXT"},
        ]
    )
    connector._service.files.return_value.get_media.return_value.execute.return_value = b"x"
    with patch("metronix.connectors.gdrive.parse_upload", return_value="x"):
        docs = asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))
    assert [d.source_id for d in docs] == ["A"]
    assert connector.take_cursor() == "T-NEXT"


def test_incremental_dedupes_repeated_file_id():
    # Same file changed twice in one feed → downloaded once.
    connector = GDriveConnector()
    connector._config = {}
    connector.load_cursor("CURSOR0")
    connector._service = _fake_changes(
        [
            {
                "changes": [_change("A", "a.txt"), _change("A", "a.txt")],
                "newStartPageToken": "T-NEXT",
            },
        ]
    )
    connector._service.files.return_value.get_media.return_value.execute.return_value = b"x"
    with patch("metronix.connectors.gdrive.parse_upload", return_value="x"):
        docs = asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))
    assert [d.source_id for d in docs] == ["A"]


def test_incremental_folder_id_logs_and_skips_change_without_parents():
    # A scoped change entry with no `parents` can't be scope-checked → skipped + logged.
    connector = GDriveConnector()
    connector._config = {"folder_id": "ROOT"}
    connector.load_cursor("CURSOR0")
    service = _fake_list([{"files": []}])  # folder BFS: ROOT has no subfolders
    _fake_changes(
        [{"changes": [_change("NP", "np.txt", parents=[])], "newStartPageToken": "T-NEXT"}],
        service=service,
    )
    connector._service = service
    with patch("metronix.connectors.gdrive.logger") as log:
        docs = asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))
    assert docs == []
    warned = [c.args[0] for c in log.warning.call_args_list if c.args]
    assert "gdrive.change.no_parents_skipped" in warned


def test_incremental_skips_removed_trashed_and_folders():
    connector = GDriveConnector()
    connector._config = {}
    connector.load_cursor("CURSOR0")
    connector._service = _fake_changes(
        [
            {
                "changes": [
                    _change("R", "gone.txt", removed=True),
                    _change("T", "trash.txt", trashed=True),
                    _change("D", "folder", mime=FOLDER_MIME),
                    _change("OK", "ok.txt"),
                ],
                "newStartPageToken": "T-NEXT",
            },
        ]
    )
    connector._service.files.return_value.get_media.return_value.execute.return_value = b"x"
    with patch("metronix.connectors.gdrive.parse_upload", return_value="x"):
        docs = asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))
    assert [d.source_id for d in docs] == ["OK"]


def test_incremental_without_cursor_falls_back_to_full_sweep():
    connector = GDriveConnector()
    connector._config = {}
    connector.load_cursor(None)  # no stored cursor
    connector._service = _fake_list(
        [
            {
                "files": [
                    {
                        "id": "A",
                        "name": "a.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-06-10T00:00:00Z",
                        "size": "2",
                    },
                ]
            }
        ]
    )
    connector._service.files.return_value.get_media.return_value.execute.return_value = b"x"
    with patch("metronix.connectors.gdrive.parse_upload", return_value="x"):
        docs = asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))
    assert [d.source_id for d in docs] == ["A"]
    assert connector.take_cursor() == "T-START"  # full-sweep token


def test_incremental_410_falls_back_to_full_sweep():
    from googleapiclient.errors import HttpError

    connector = GDriveConnector()
    connector._config = {}
    connector.load_cursor("STALE")
    service = _fake_list(
        [
            {
                "files": [
                    {
                        "id": "A",
                        "name": "a.txt",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-06-10T00:00:00Z",
                        "size": "2",
                    },
                ]
            }
        ]
    )
    resp = MagicMock()
    resp.status = 410
    service.changes.return_value.list.return_value.execute.side_effect = HttpError(
        resp, b"fullSyncRequired"
    )
    service.files.return_value.get_media.return_value.execute.return_value = b"x"
    connector._service = service
    with patch("metronix.connectors.gdrive.parse_upload", return_value="x"):
        docs = asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))
    assert [d.source_id for d in docs] == ["A"]
    assert connector.take_cursor() == "T-START"


def test_incremental_non_410_propagates():
    from googleapiclient.errors import HttpError

    connector = GDriveConnector()
    connector._config = {}
    connector.load_cursor("CURSOR0")
    service = MagicMock()
    resp = MagicMock()
    resp.status = 403
    service.changes.return_value.list.return_value.execute.side_effect = HttpError(
        resp, b"rateLimitExceeded"
    )
    connector._service = service
    with pytest.raises(HttpError):
        asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))


def test_incremental_shared_drive_passes_drive_id():
    connector = GDriveConnector()
    connector._config = {"shared_drive_id": "D1"}
    connector.load_cursor("CURSOR0")
    connector._service = _fake_changes([{"changes": [], "newStartPageToken": "T-NEXT"}])
    asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))
    _, kwargs = connector._service.changes.return_value.list.call_args
    assert kwargs["driveId"] == "D1"
    assert kwargs["includeItemsFromAllDrives"] is True
    assert kwargs["supportsAllDrives"] is True


def test_folder_scope_ids_bfs():
    connector = GDriveConnector()
    connector._config = {"folder_id": "ROOT"}
    # ROOT's folder children: SUB1; SUB1's folder children: SUB2; SUB2: none.
    connector._service = _fake_list(
        [
            {"files": [{"id": "SUB1", "name": "s1", "mimeType": FOLDER_MIME}]},
            {"files": [{"id": "SUB2", "name": "s2", "mimeType": FOLDER_MIME}]},
            {"files": []},
        ]
    )
    assert connector._folder_scope_ids() == {"ROOT", "SUB1", "SUB2"}


def test_incremental_folder_id_filters_by_ancestry():
    connector = GDriveConnector()
    connector._config = {"folder_id": "ROOT"}
    connector.load_cursor("CURSOR0")
    # Service answers BOTH the folder-BFS (files.list) and changes.list.
    service = _fake_list(
        [
            {"files": [{"id": "SUB1", "name": "s1", "mimeType": FOLDER_MIME}]},  # ROOT children
            {"files": []},  # SUB1 children
        ]
    )
    _fake_changes(
        [
            {
                "changes": [
                    _change("IN", "in.txt", parents=["SUB1"]),  # inside subtree → kept
                    _change("OUT", "out.txt", parents=["OTHER"]),  # outside → dropped
                ],
                "newStartPageToken": "T-NEXT",
            },
        ],
        service=service,
    )
    service.files.return_value.get_media.return_value.execute.return_value = b"x"
    connector._service = service
    with patch("metronix.connectors.gdrive.parse_upload", return_value="x"):
        docs = asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))
    assert [d.source_id for d in docs] == ["IN"]


def test_incremental_folder_id_includes_file_in_new_subfolder():
    # A subfolder created within the same change window + a file inside it: the
    # file must NOT be dropped even though the initial scope BFS didn't know the
    # subfolder yet (#2).
    connector = GDriveConnector()
    connector._config = {"folder_id": "ROOT"}
    connector.load_cursor("CURSOR0")
    service = _fake_list([{"files": []}])  # ROOT has no pre-existing subfolders
    _fake_changes(
        [
            {
                "changes": [
                    # File change appears BEFORE its parent-folder change in the feed
                    # → fixpoint scope-growth must still include it.
                    _change("F", "f.txt", parents=["NEWSUB"]),
                    _change("NEWSUB", "newsub", mime=FOLDER_MIME, parents=["ROOT"]),
                ],
                "newStartPageToken": "T-NEXT",
            },
        ],
        service=service,
    )
    service.files.return_value.get_media.return_value.execute.return_value = b"x"
    connector._service = service
    with patch("metronix.connectors.gdrive.parse_upload", return_value="x"):
        docs = asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))
    assert [d.source_id for d in docs] == ["F"]


def test_incremental_holds_cursor_on_fetch_error():
    # A file that fails to fetch must NOT advance the cursor, so the next sync
    # replays and retries (#1). take_cursor() returns None → orchestrator keeps
    # the prior token.
    connector = GDriveConnector()
    connector._config = {}
    connector.load_cursor("CURSOR0")
    connector._service = _fake_changes(
        [
            {"changes": [_change("BAD", "bad.txt")], "newStartPageToken": "T-NEXT"},
        ]
    )
    connector._service.files.return_value.get_media.return_value.execute.return_value = b"x"
    with patch("metronix.connectors.gdrive.parse_upload", side_effect=ValueError("boom")):
        docs = asyncio.run(connector.fetch("ws1", since=datetime(2026, 1, 1, tzinfo=UTC)))
    assert docs == []
    assert connector.take_cursor() is None  # cursor held, not advanced to T-NEXT


def test_process_file_skips_binary_without_size():
    # Unknown size must not bypass the memory guard → skip, don't download.
    connector = GDriveConnector()
    connector._service = MagicMock()
    doc = connector._process_file(_doc_meta("application/pdf", "nosize.pdf"), "ws1")
    assert doc is None
    connector._service.files.return_value.get_media.assert_not_called()
