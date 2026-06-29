# Jira Actions

Interact with Jira: search issues, get details, create/update tickets.

## When to use
- User asks about Jira tickets, sprints, or project status
- User wants to create or update a Jira issue
- User mentions ticket IDs (e.g., PROJ-123)

## Triggers
- jira
- ticket
- issue
- sprint

## Tags
- jira
- issues
- project-management
- tickets

## Tool Calls

### Search Issues
```json
{
  "tool": "http_request",
  "parameters": {
    "method": "GET",
    "url": "{jira_base_url}/rest/api/3/search",
    "params": {
      "jql": "<JQL query>",
      "maxResults": 10,
      "fields": "summary,status,assignee,priority,updated"
    }
  }
}
```

### Get Issue Details
```json
{
  "tool": "http_request",
  "parameters": {
    "method": "GET",
    "url": "{jira_base_url}/rest/api/3/issue/{issue_key}",
    "params": {
      "fields": "summary,description,status,assignee,priority,comment"
    }
  }
}
```

### Create Issue
```json
{
  "tool": "http_request",
  "parameters": {
    "method": "POST",
    "url": "{jira_base_url}/rest/api/3/issue",
    "body": {
      "fields": {
        "project": {"key": "<project_key>"},
        "summary": "<title>",
        "description": "<description in ADF>",
        "issuetype": {"name": "Task"}
      }
    }
  }
}
```

## Behavior
1. Parse user intent: search, view, create, or update
2. Build the appropriate API call using workspace connection credentials
3. Format results clearly: ticket key, summary, status, assignee
4. For creation: confirm details with user before executing
5. Always include Jira links in responses
