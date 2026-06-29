# Confluence Actions

Interact with Confluence: search pages, view content, create/update pages.

## When to use
- User asks about Confluence pages or documentation
- User wants to find specific wiki content
- User needs to create or update a Confluence page

## Triggers
- confluence
- wiki
- page
- documentation

## Tags
- confluence
- wiki
- documentation
- knowledge-base

## Tool Calls

### Search Pages (CQL)
```json
{
  "tool": "http_request",
  "parameters": {
    "method": "GET",
    "url": "{confluence_base_url}/rest/api/content/search",
    "params": {
      "cql": "type=page AND text ~ \"<search terms>\"",
      "limit": 10,
      "expand": "metadata.labels"
    }
  }
}
```

### Get Page Content
```json
{
  "tool": "http_request",
  "parameters": {
    "method": "GET",
    "url": "{confluence_base_url}/rest/api/content/{page_id}",
    "params": {
      "expand": "body.storage,metadata.labels,version"
    }
  }
}
```

### Create Page
```json
{
  "tool": "http_request",
  "parameters": {
    "method": "POST",
    "url": "{confluence_base_url}/rest/api/content",
    "body": {
      "type": "page",
      "title": "<page title>",
      "space": {"key": "<space_key>"},
      "body": {
        "storage": {
          "value": "<HTML content>",
          "representation": "storage"
        }
      }
    }
  }
}
```

## Behavior
1. Parse user intent: search, view, create, or update
2. Use CQL for search queries (Confluence Query Language)
3. Convert HTML body to readable text when displaying content
4. For creation: confirm title and content structure with user
5. Always include Confluence page links in responses
6. Show page labels/tags when relevant
