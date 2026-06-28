# Pi

## Recommended mode

Use whichever surface Pi supports best:

- MCP if Pi supports external MCP servers
- OpenAI-compatible API if Pi only supports custom chat providers

## MCP values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:     <stable-pi-agent-id>
```

## OpenAI-compatible values

```text
Base URL: http://localhost:8001/v1
Model:    metatron-rag-<workspace_id>
Key:      <METATRON_OPENAI_COMPAT_KEY>
```

## Recommendation

If Pi supports both, choose MCP first. If it only supports chat providers, use `/v1`.

## Verify

- MCP path: run `metatron_status`
- OpenAI-compatible path: send one test chat request against `metatron-rag-<workspace_id>`

## Note

This guide assumes Pi is acting as a client runtime. If you meant a different "Pi," rename
the guide later before future-us has to become archaeologists.
