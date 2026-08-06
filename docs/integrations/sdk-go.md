# Go SDK

> **MCP authentication mode:** Local `AUTH_ENABLED=false` MCP examples use
> `METRONIX_MCP_API_KEY`. Hosted `AUTH_ENABLED=true` MCP clients use a user JWT instead;
> the shared key is ignored.

## Recommended surfaces

Use:

- `/v1` for chat-style integrations
- `/api/v1` for direct application control
- `/mcp` for tool-driven agent runtimes

## OpenAI-compatible values

```text
Base URL: http://localhost:8000/v1
Model:    metronix-rag-<workspace_id>
Key:      <METRONIX_OPENAI_COMPAT_KEY>
```

## REST base URL

```text
http://localhost:8000/api/v1
```

## MCP values

```text
URL:            http://localhost:8000/mcp
Authorization:  Bearer <METRONIX_MCP_API_KEY>
X-Agent-Id:     <stable-go-agent-id>
```

## Verify

After setup, confirm the connection works:

1. Send a GET request to `http://localhost:8000/health` and confirm a 200 OK response.
2. For OpenAI-compatible usage, send a test chat completion request to `http://localhost:8000/v1/chat/completions` with the correct API key.
3. For MCP usage, call `metronix_status(workspace_id="MTRNIX")` and confirm a status response.

## Troubleshooting

**Connection refused:** Verify the stack is running (`curl http://localhost:8000/health`).

**Authentication errors on `/v1`:** Confirm the API key matches `METRONIX_OPENAI_COMPAT_KEY` in `.env`.

**Authentication errors on `/mcp`:** Confirm the `Authorization: Bearer <key>` header matches `METRONIX_MCP_API_KEY` in `.env`, and that `X-Agent-Id` is included in every request.

## Recommendation

If you're writing a service in Go, use REST or `/v1` first. Reach for MCP when you need
explicit agent tools and durable memory behavior, not just plain request-response chat.
