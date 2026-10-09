# VS Code (GitHub Copilot) Integration

> **Which key to use.** With `AUTH_ENABLED=false`, the shared `METRONIX_MCP_API_KEY` opens
> `/mcp` but only `metronix_status` and `metronix_search_fast` work with it; the
> `metronix_memory_*` tools return `AUTH_REQUIRED`. For memory, use a personal `mtk_` API key —
> see [Example in 5 minutes](../../README.md#example-in-5-minutes-store-and-find-a-memory)
> (steps 2–3) for how to create one. For hosted `AUTH_ENABLED=true`, put a user JWT in the same
> Bearer header.

Register Metronix as an HTTP MCP server in VS Code, so Copilot Chat can call the `metronix_*` tools.

## Configuration

Create `.vscode/mcp.json` in the workspace (or open the user-level file with the
**MCP: Open User Configuration** command):

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "metronix-key",
      "description": "Metronix personal API key (mtk_...)",
      "password": true
    }
  ],
  "servers": {
    "metronix": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${input:metronix-key}",
        "X-Agent-Id": "my-agent"
      }
    }
  }
}
```

- The top-level key is `servers` (not `mcpServers`, which Cursor and Claude Desktop use).
- `"type": "http"` is the remote/streamable-HTTP transport.
- VS Code prompts for the key the first time the server starts and keeps it out of the file.
  Do not commit a real key into `.vscode/mcp.json`.
- `X-Agent-Id` is a stable id you choose: 1–64 characters from `A–Z a–z 0–9 . _ -`. Use the same
  value as `agent_id` in memory tool arguments.
- The URL is the host-published port of the `metronix-core` container. From another container on
  the Compose network use `http://metronix-core:8000/mcp`.

## Verify

1. Run **MCP: List Servers**, select `metronix`, and choose an action to start it (VS Code shows
   a trust dialog the first time a server starts or its configuration changes).
2. Ask Copilot Chat to call `metronix_status`, then `metronix_memory_list` with `agent_id` set to
   your `X-Agent-Id` value and `workspace_id` set to `MTRNIX`.

## What was verified

| Item | How |
| --- | --- |
| Server accepts `url`, `Authorization: Bearer mtk_…` and `X-Agent-Id` exactly as configured above | **Run.** `initialize`, `tools/list`, `metronix_memory_store`, `metronix_memory_search`, `metronix_memory_list` with those headers against a stack built from `131d6b0` |
| Shared key cannot use `metronix_memory_*` | **Run.** `AUTH_REQUIRED` |
| The JSON above parses | **Run.** `jq .` |
| `.vscode/mcp.json` layout (`servers`, `type: http`, `headers`, `inputs` with `promptString` and `password: true`, `${input:id}`), user-config command, **MCP: List Servers**, trust prompt | **Documentation only**: [VS Code MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers) and the [MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration). VS Code itself was not run |

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`).

**HTTP 401 from `/mcp`:** The Bearer value is missing or wrong (an unknown `mtk_` key returns 401). Check the key you entered when the server started.

**`AUTH_REQUIRED` from `metronix_memory_*`:** You are using the shared `METRONIX_MCP_API_KEY`. Switch to a personal `mtk_` key.

**`INVALID_PARAMS: X-Agent-Id must match the agent_id tool argument`:** `agent_id` in the tool arguments must equal the `X-Agent-Id` header.
