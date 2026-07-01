from datetime import datetime

from metronix.connectors.github_processing import (
    _csv,
    _parse_dt,
    issue_to_document,
    issue_to_markdown,
    pr_to_document,
    pr_to_markdown,
)

ISSUE = {
    "number": 42,
    "title": "Login button is broken",
    "state": "closed",
    "body": "Clicking login does nothing.",
    "html_url": "https://github.com/acme/web/issues/42",
    "user": "alice",
    "labels": ["bug", "ui"],
    "assignees": ["bob"],
    "created_at": "2026-01-02T10:00:00Z",
    "updated_at": "2026-01-03T12:30:00Z",
    "closed_at": "2026-01-04T09:00:00Z",
    "comments": [
        {"author": "bob", "created_at": "2026-01-03T11:00:00Z", "body": "On it."},
    ],
}


def test_csv_joins_non_empty():
    assert _csv(["a", "", "b", None]) == "a, b"
    assert _csv(None) == ""


def test_parse_dt_handles_z_and_none():
    assert _parse_dt("2026-01-02T10:00:00Z") == datetime.fromisoformat(
        "2026-01-02T10:00:00+00:00"
    )
    assert _parse_dt(None) is None
    assert _parse_dt("not-a-date") is None


def test_issue_markdown_contains_title_body_and_comment():
    md = issue_to_markdown(ISSUE, "acme/web")
    assert "[acme/web#42] Login button is broken" in md
    assert "Clicking login does nothing." in md
    assert "bob" in md and "On it." in md
    assert "**State:** closed" in md


def test_issue_to_document_fields_and_string_metadata():
    doc = issue_to_document(ISSUE, "acme", "web", "ws1")
    assert doc.source_type == "github"
    assert doc.source_id == "gh-issue-acme-web-42"
    assert doc.workspace_id == "ws1"
    assert doc.title == "[acme/web#42] Login button is broken"
    assert doc.url == "https://github.com/acme/web/issues/42"
    assert doc.author == "alice"
    # metadata values are all strings
    assert all(isinstance(v, str) for v in doc.metadata.values())
    assert doc.metadata["labels"] == "bug, ui"
    assert doc.metadata["assignees"] == "bob"
    assert doc.metadata["state"] == "closed"
    assert doc.metadata["number"] == "42"
    assert doc.created_at == datetime.fromisoformat("2026-01-02T10:00:00+00:00")
    assert doc.updated_at == datetime.fromisoformat("2026-01-03T12:30:00+00:00")


PR = {
    "number": 7,
    "title": "Add OAuth login",
    "state": "closed",
    "body": "Implements OAuth.",
    "html_url": "https://github.com/acme/web/pull/7",
    "user": "carol",
    "labels": ["feature"],
    "assignees": [],
    "merged": True,
    "base": "main",
    "head": "feat/oauth",
    "created_at": "2026-02-01T10:00:00Z",
    "updated_at": "2026-02-05T12:00:00Z",
    "closed_at": "2026-02-05T12:00:00Z",
    "comments": [{"author": "dave", "created_at": "2026-02-02T10:00:00Z", "body": "LGTM"}],
    "review_comments": [
        {"author": "dave", "created_at": "2026-02-02T11:00:00Z", "body": "nit: rename", "path": "auth.py"},
    ],
}


def test_pr_markdown_has_merge_info_and_review_comments():
    md = pr_to_markdown(PR, "acme/web")
    assert "[acme/web PR#7] Add OAuth login" in md
    assert "main" in md and "feat/oauth" in md
    assert "LGTM" in md
    assert "auth.py" in md and "nit: rename" in md


def test_pr_to_document_merged_serialized_as_string():
    doc = pr_to_document(PR, "acme", "web", "ws1")
    assert doc.source_id == "gh-pr-acme-web-7"
    assert doc.metadata["type"] == "github_pr"
    assert doc.metadata["merged"] == "true"
    assert doc.metadata["base"] == "main"
    assert doc.metadata["head"] == "feat/oauth"
    assert all(isinstance(v, str) for v in doc.metadata.values())
    assert doc.title == "[acme/web PR#7] Add OAuth login"
