from metronix.connectors.gdrive_processing import (
    FOLDER_MIME,
    build_document,
    export_format,
)


def test_export_format_google_native():
    assert export_format("application/vnd.google-apps.document")[0] == "text/markdown"
    assert export_format("application/vnd.google-apps.spreadsheet")[0] == "text/csv"
    assert export_format("application/vnd.google-apps.presentation")[0] == "text/plain"


def test_export_format_none_for_binary_and_folder():
    assert export_format("application/pdf") is None
    assert export_format(FOLDER_MIME) is None
    assert export_format("") is None


def test_build_document_owner_from_display_name():
    meta = {
        "id": "F1",
        "name": "Design Doc",
        "mimeType": "application/vnd.google-apps.document",
        "modifiedTime": "2026-06-01T12:00:00.000Z",
        "webViewLink": "https://docs.google.com/d/F1",
        "owners": [{"displayName": "Alice", "emailAddress": "a@x.com"}],
    }
    doc = build_document(meta, "# body", "ws1")
    assert doc.source_type == "gdrive"
    assert doc.source_id == "F1"
    assert doc.title == "Design Doc"
    assert doc.content == "# body"
    assert doc.url == "https://docs.google.com/d/F1"
    assert doc.author == "Alice"
    assert doc.workspace_id == "ws1"
    assert doc.metadata["file_id"] == "F1"
    assert doc.metadata["mime_type"] == "application/vnd.google-apps.document"
    assert doc.metadata["owner"] == "Alice"  # reuses computed author, not owners[0]


def test_build_document_owner_safe_when_owners_missing():
    # Shared-Drive items have no `owners` key — must NOT raise, author == "".
    meta = {
        "id": "F2",
        "name": "Shared File",
        "mimeType": "application/pdf",
        "modifiedTime": "2026-06-02T00:00:00Z",
    }
    doc = build_document(meta, "text", "ws1")
    assert doc.author == ""
    assert doc.metadata["owner"] == ""
    assert doc.url == ""  # missing webViewLink → empty string, not KeyError


def test_build_document_falls_back_to_email():
    meta = {
        "id": "F3",
        "name": "n",
        "mimeType": "application/pdf",
        "owners": [{"emailAddress": "bob@x.com"}],
    }
    assert build_document(meta, "t", "ws1").author == "bob@x.com"
