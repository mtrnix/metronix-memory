# GitHub Actions

Interact with GitHub: search repos, view issues/PRs, check CI status.

## When to use
- User asks about GitHub repositories, issues, or pull requests
- User wants to check CI/CD pipeline status
- User mentions repo names or PR numbers

## Triggers
- github
- repo
- pull request
- PR
- CI

## Tags
- github
- repositories
- pull-requests
- ci-cd

## Tool Calls

### Search Repositories
```json
{
  "tool": "http_request",
  "parameters": {
    "method": "GET",
    "url": "https://api.github.com/search/repositories",
    "params": {
      "q": "org:{org} <search terms>",
      "per_page": 10
    }
  }
}
```

### List Open PRs
```json
{
  "tool": "http_request",
  "parameters": {
    "method": "GET",
    "url": "https://api.github.com/repos/{owner}/{repo}/pulls",
    "params": {
      "state": "open",
      "per_page": 10
    }
  }
}
```

### Get PR Details
```json
{
  "tool": "http_request",
  "parameters": {
    "method": "GET",
    "url": "https://api.github.com/repos/{owner}/{repo}/pulls/{number}"
  }
}
```

## Behavior
1. Identify the target repository from context or user mention
2. Build the appropriate GitHub API call
3. Format results: repo name, description, PR title, status, author
4. Include direct GitHub links for all referenced items
5. For CI status: show check suite results (pass/fail/pending)
