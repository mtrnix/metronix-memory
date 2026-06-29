"""Tests for connectors/jira_processing.py — ADF extraction, issue parsing, Markdown."""

from __future__ import annotations

from metronix.connectors.jira_processing import (
    extract_adf_text,
    jira_issue_to_markdown,
    process_jira_issue,
)


class TestExtractAdfText:
    def test_none_returns_empty(self) -> None:
        assert extract_adf_text(None) == ""

    def test_plain_string_returns_itself(self) -> None:
        assert extract_adf_text("hello world") == "hello world"

    def test_text_node(self) -> None:
        node = {"type": "text", "text": "some text"}
        assert extract_adf_text(node) == "some text"

    def test_paragraph_with_text(self) -> None:
        node = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Hello "},
                {"type": "text", "text": "world"},
            ],
        }
        result = extract_adf_text(node)
        assert "Hello" in result
        assert "world" in result

    def test_nested_doc_with_paragraphs(self) -> None:
        node = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "First paragraph."}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Second paragraph."}],
                },
            ],
        }
        result = extract_adf_text(node)
        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_heading(self) -> None:
        node = {
            "type": "heading",
            "content": [{"type": "text", "text": "Title"}],
        }
        result = extract_adf_text(node)
        assert "Title" in result

    def test_list_input(self) -> None:
        nodes = [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
        ]
        assert extract_adf_text(nodes) == "ab"

    def test_empty_dict_returns_empty(self) -> None:
        assert extract_adf_text({}) == ""

    def test_codeblock(self) -> None:
        node = {
            "type": "codeBlock",
            "content": [{"type": "text", "text": "print('hello')"}],
        }
        result = extract_adf_text(node)
        assert "print('hello')" in result


class TestProcessJiraIssue:
    def _make_issue(self, **overrides) -> dict:
        base = {
            "id": "10001",
            "key": "PROJ-123",
            "fields": {
                "summary": "Fix the login bug",
                "status": {"name": "In Progress"},
                "assignee": {"displayName": "Alice"},
                "reporter": {"displayName": "Bob"},
                "created": "2024-01-15T10:00:00.000+0000",
                "updated": "2024-01-16T14:00:00.000+0000",
                "priority": {"name": "High"},
                "issuetype": {"name": "Bug"},
                "description": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Login fails for SSO users."}],
                        }
                    ],
                },
                "comment": {
                    "comments": [
                        {
                            "author": {"displayName": "Charlie"},
                            "created": "2024-01-15T12:00:00.000+0000",
                            "body": {
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {"type": "text", "text": "Investigating now."}
                                        ],
                                    }
                                ],
                            },
                        }
                    ],
                },
            },
            "changelog": {
                "histories": [
                    {
                        "author": {"displayName": "Alice"},
                        "created": "2024-01-15T11:00:00.000+0000",
                        "items": [
                            {
                                "field": "status",
                                "fromString": "Open",
                                "toString": "In Progress",
                            }
                        ],
                    }
                ],
            },
        }
        base.update(overrides)
        return base

    def test_basic_fields(self) -> None:
        result = process_jira_issue(self._make_issue())
        assert result["key"] == "PROJ-123"
        assert result["summary"] == "Fix the login bug"
        assert result["status"] == "In Progress"
        assert result["assignee"] == "Alice"
        assert result["reporter"] == "Bob"
        assert result["priority"] == "High"
        assert result["issuetype"] == "Bug"

    def test_description_extracted(self) -> None:
        result = process_jira_issue(self._make_issue())
        assert "Login fails for SSO users" in result["description"]

    def test_comments_parsed(self) -> None:
        result = process_jira_issue(self._make_issue())
        assert len(result["comments"]) == 1
        assert result["comments"][0]["author"] == "Charlie"
        assert "Investigating" in result["comments"][0]["text"]

    def test_changelog_parsed(self) -> None:
        result = process_jira_issue(self._make_issue())
        assert len(result["changes"]) == 1
        assert result["changes"][0]["field"] == "status"
        assert result["changes"][0]["from"] == "Open"
        assert result["changes"][0]["to"] == "In Progress"

    def test_no_assignee(self) -> None:
        issue = self._make_issue()
        issue["fields"]["assignee"] = None
        result = process_jira_issue(issue)
        assert result["assignee"] is None

    def test_no_description(self) -> None:
        issue = self._make_issue()
        issue["fields"]["description"] = None
        result = process_jira_issue(issue)
        assert result["description"] == ""

    def test_json_string_input(self) -> None:
        import json

        issue = self._make_issue()
        json_str = json.dumps(issue)
        result = process_jira_issue(json_str)
        assert result["key"] == "PROJ-123"

    def test_json_bytes_input(self) -> None:
        import json

        issue = self._make_issue()
        json_bytes = json.dumps(issue).encode("utf-8")
        result = process_jira_issue(json_bytes)
        assert result["key"] == "PROJ-123"


class TestJiraIssueToMarkdown:
    def test_basic_markdown(self) -> None:
        data = {
            "key": "PROJ-1",
            "summary": "Test issue",
            "status": "Open",
            "issuetype": "Task",
            "priority": "Medium",
            "assignee": "Alice",
            "reporter": "Bob",
            "created": "2024-01-01",
            "updated": "2024-01-02",
            "description": "Something needs fixing.",
            "comments": [],
            "changes": [],
        }
        md = jira_issue_to_markdown(data)
        assert "# [PROJ-1] Test issue" in md
        assert "**Status:** Open" in md
        assert "**Type:** Task" in md
        assert "**Priority:** Medium" in md
        assert "**Assignee:** Alice" in md
        assert "## Description" in md
        assert "Something needs fixing." in md

    def test_with_comments(self) -> None:
        data = {
            "key": "X-1",
            "summary": "S",
            "status": "Done",
            "description": "",
            "comments": [
                {"author": "Eve", "created": "2024-02-01", "text": "Looks good."},
            ],
            "changes": [],
        }
        md = jira_issue_to_markdown(data)
        assert "## Comments" in md
        assert "**Eve**" in md
        assert "Looks good." in md

    def test_with_changelog(self) -> None:
        data = {
            "key": "X-2",
            "summary": "S",
            "status": "Done",
            "description": "",
            "comments": [],
            "changes": [
                {
                    "author": "Frank",
                    "created": "2024-03-01",
                    "field": "status",
                    "from": "Open",
                    "to": "Done",
                },
            ],
        }
        md = jira_issue_to_markdown(data)
        assert "## Changelog" in md
        assert "Frank" in md
        assert "status" in md

    def test_no_optional_fields(self) -> None:
        data = {
            "key": "MIN-1",
            "summary": "Minimal",
            "status": "Open",
            "description": "",
            "comments": [],
            "changes": [],
        }
        md = jira_issue_to_markdown(data)
        assert "# [MIN-1] Minimal" in md
        assert "## Description" not in md
        assert "## Comments" not in md
        assert "## Changelog" not in md
