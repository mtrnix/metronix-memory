from metatron.ingestion.upload import ALLOWED_UPLOAD_EXTENSIONS, is_allowed_upload


def test_allowlist_contents():
    assert frozenset(
        {".pdf", ".docx", ".xlsx", ".csv", ".html", ".htm", ".txt", ".md"}
    ) == ALLOWED_UPLOAD_EXTENSIONS


def test_is_allowed_upload_accepts_known_extensions():
    assert is_allowed_upload("report.PDF") is True
    assert is_allowed_upload("data.csv") is True
    assert is_allowed_upload("notes.md") is True


def test_is_allowed_upload_rejects_unknown_and_empty():
    assert is_allowed_upload("archive.zip") is False
    assert is_allowed_upload("noext") is False
    assert is_allowed_upload("") is False
