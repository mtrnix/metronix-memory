from metronix.core.models import Document
from metronix.ingestion.upload import (
    ALLOWED_UPLOAD_EXTENSIONS,
    build_upload_document,
    is_allowed_upload,
    parse_upload,
)


def test_allowlist_contents():
    assert (
        frozenset({".pdf", ".docx", ".xlsx", ".csv", ".html", ".htm", ".txt", ".md"})
        == ALLOWED_UPLOAD_EXTENSIONS
    )


def test_is_allowed_upload_accepts_known_extensions():
    assert is_allowed_upload("report.PDF") is True
    assert is_allowed_upload("data.csv") is True
    assert is_allowed_upload("notes.md") is True


def test_is_allowed_upload_rejects_unknown_and_empty():
    assert is_allowed_upload("archive.zip") is False
    assert is_allowed_upload("noext") is False
    assert is_allowed_upload("") is False


def test_parse_upload_plain_text():
    assert parse_upload("notes.txt", b"hello world") == "hello world"


def test_parse_upload_markdown_passthrough():
    assert parse_upload("readme.md", b"# Title\n\nbody") == "# Title\n\nbody"


def test_parse_upload_latin1_fallback_does_not_raise():
    # Invalid UTF-8 byte 0xff must not raise; decoded with replacement.
    out = parse_upload("weird.txt", b"caf\xff")
    assert isinstance(out, str)


def test_parse_upload_pdf_delegates_to_processor(monkeypatch):
    called = {}

    def fake_pdf(raw, name):
        called["args"] = (raw, name)
        return "PDF TEXT"

    monkeypatch.setattr("metronix.ingestion.processors.pdf.extract_text_from_pdf", fake_pdf)
    assert parse_upload("doc.pdf", b"%PDF-1.4") == "PDF TEXT"
    assert called["args"] == (b"%PDF-1.4", "doc.pdf")


def test_build_upload_document_field_mapping():
    doc = build_upload_document(
        filename="quarterly.pdf",
        text="extracted body",
        user_id="alice",
        workspace_id="ws_1",
    )
    assert isinstance(doc, Document)
    assert doc.source_id == "quarterly.pdf"
    assert doc.title == "quarterly.pdf"
    assert doc.content == "extracted body"
    assert doc.source_type == "upload"
    assert doc.source_role == "user_upload"
    assert doc.author == "alice"
    assert doc.workspace_id == "ws_1"
    assert doc.url == ""
