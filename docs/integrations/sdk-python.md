# Python SDK

> **MCP authentication mode:** Local `AUTH_ENABLED=false` MCP examples use
> `METRONIX_MCP_API_KEY`. Hosted `AUTH_ENABLED=true` MCP clients use a user JWT instead;
> the shared key is ignored.

## Recommended surfaces

Pick the simplest interface that matches the job:

- OpenAI-compatible API for chat-style usage
- REST API for app integration
- MCP for tool-driven agent runtimes

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
X-Agent-Id:     <stable-python-agent-id>
```

## Verify

After setup, confirm the connection works:

1. Send a GET request to `http://localhost:8000/health` and confirm a 200 OK response.
2. For OpenAI-compatible usage, send a test chat completion request to `http://localhost:8000/v1/chat/completions` with the correct API key.
3. For MCP usage, call `metronix_status(workspace_id="MTRNIX")` and confirm a status response.

## Troubleshooting

**Connection refused:** Verify the stack is running (`curl http://localhost:8000/health`).

**Authentication errors on `/v1`:** Confirm the API key passed in your Python client matches `METRONIX_OPENAI_COMPAT_KEY` in `.env`.

**Authentication errors on `/mcp`:** Confirm the `Authorization: Bearer <key>` header matches `METRONIX_MCP_API_KEY` in `.env`, and that `X-Agent-Id` is included in every request.

## Recommendation

If you are writing an application backend, start with REST or `/v1`.
If you are wiring an autonomous agent, start with MCP.
