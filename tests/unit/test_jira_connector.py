"""Tests for Jira connector URL generation."""

from metatron.connectors.jira import JiraConnector


class TestJiraDocumentUrl:
    def test_issue_to_document_sets_url(self) -> None:
        connector = JiraConnector()
        connector._config = {"url": "https://mycompany.atlassian.net"}
        raw_issue = {
            "key": "MTRNIX-42",
            "fields": {
                "summary": "Test issue",
                "description": "Body text",
                "issuetype": {"name": "Task"},
                "status": {"name": "Open"},
                "priority": {"name": "Medium"},
                "creator": {"displayName": "Alice", "emailAddress": "a@co.il"},
                "reporter": {"displayName": "Alice", "emailAddress": "a@co.il"},
                "assignee": None,
                "created": "2026-01-01T00:00:00.000+0000",
                "updated": "2026-01-02T00:00:00.000+0000",
                "resolutiondate": None,
                "labels": [],
                "components": [],
                "comment": {"comments": []},
            },
        }
        doc = connector._issue_to_document(raw_issue, workspace_id="ws1")
        assert doc.url == "https://mycompany.atlassian.net/browse/MTRNIX-42"

    def test_issue_url_strips_trailing_slash(self) -> None:
        connector = JiraConnector()
        connector._config = {"url": "https://mycompany.atlassian.net/"}
        raw_issue = {
            "key": "PROJ-1",
            "fields": {
                "summary": "Slash test",
                "description": "",
                "issuetype": {"name": "Bug"},
                "status": {"name": "Open"},
                "priority": {"name": "Low"},
                "creator": {"displayName": "Bob", "emailAddress": "b@co.il"},
                "reporter": {"displayName": "Bob", "emailAddress": "b@co.il"},
                "assignee": None,
                "created": "2026-01-01T00:00:00.000+0000",
                "updated": "2026-01-01T00:00:00.000+0000",
                "resolutiondate": None,
                "labels": [],
                "components": [],
                "comment": {"comments": []},
            },
        }
        doc = connector._issue_to_document(raw_issue, workspace_id="ws1")
        assert doc.url == "https://mycompany.atlassian.net/browse/PROJ-1"
