# Go SDK

## Recommended surfaces

Use:

- `/v1` for chat-style integrations
- `/api/v1` for direct application control
- `/mcp` for tool-driven agent runtimes

## OpenAI-compatible values

```text
Base URL: http://localhost:8001/v1
Model:    metatron-rag-<workspace_id>
Key:      <METATRON_OPENAI_COMPAT_KEY>
```

## REST base URL

```text
http://localhost:8001/api/v1
```

## MCP values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:     <stable-go-agent-id>
```

## Recommendation

If you're writing a service in Go, use REST or `/v1` first. Reach for MCP when you need
explicit agent tools and durable memory behavior, not just plain request-response chat.
