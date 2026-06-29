# NanoBot

## Recommended mode

Use Metronix Memory through MCP if NanoBot supports external MCP servers. Otherwise use the
OpenAI-compatible endpoint for chat-style access.

## MCP values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:     <stable-nanobot-agent-id>
```

## OpenAI-compatible values

```text
Base URL: http://localhost:8001/v1
Model:    metatron-rag-<workspace_id>
Key:      <METATRON_OPENAI_COMPAT_KEY>
```

## Recommendation

If NanoBot is supposed to remember things durably, pick MCP. If it's just a chat shell,
`/v1` is enough to get moving.
