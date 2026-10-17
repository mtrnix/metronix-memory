# VS Code (GitHub Copilot) Integration

> **Which key to use.** With `AUTH_ENABLED=false`, the shared `METRONIX_MCP_API_KEY` opens
> `/mcp` but only `metronix_status` and `metronix_search_fast` work with it; the
> `metronix_memory_*` tools return `AUTH_REQUIRED`. For memory, use a personal `mtk_` API key —
> see [Example in 5 minutes](../../README.md#example-in-5-minutes-store-and-find-a-memory)
> (steps 2–3) for how to create one. For hosted `AUTH_ENABLED=true`, put a user JWT in the same
> Bearer header.

Register Metronix as an HTTP MCP server in VS Code, so Copilot Chat can call the `metronix_*` tools.

## Configuration

Open the user-level file with the **MCP: Open User Configuration** command (or create
`.vscode/mcp.json` in a workspace) and add:

```json
{
  "servers": {
    "metronix": {
      "type": "http",
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer mtk_...",
        "X-Agent-Id": "my-agent"
      }
    }
  }
}
```

- The top-level key is `servers` (not `mcpServers`, which Cursor and Claude Desktop use).
- `"type": "http"` is the remote/streamable-HTTP transport.
- Replace `mtk_...` with your personal key. **The key is written into the file, so keep that file
  out of version control.** The user-level file lives in your VS Code profile, outside any
  repository. If you use `.vscode/mcp.json` in a repository, add it to `.gitignore` and never
  commit it.
- Paste the key **without a trailing space or newline.** Metronix compares it exactly, and a
  trailing space returns 401. When you copy it from a file, use `printf %s "$MTK" | pbcopy` (macOS)
  rather than `echo`.
- `X-Agent-Id` is a stable id you choose: 1–64 characters from `A–Z a–z 0–9 . _ -`. Use the same
  value as `agent_id` in memory tool arguments.
- The URL is the host-published port of the `metronix-core` container. From another container on
  the Compose network use `http://metronix-core:8000/mcp`.
- VS Code can also prompt for the key with an `inputs` entry (`promptString`, `"password": true`)
  and `"Authorization": "Bearer ${input:metronix-key}"`. That form was **not** verified here:
  the attempts with it ended in the OAuth fallback described below, in a session where other
  things were also wrong, so the cause was not isolated.

## Verify

Use the **regular Copilot Chat in Agent mode with a local session**. Do not use a Copilot CLI
or other Agent Host session: starting the server there fails with `Cannot start an MCP server
before the session runtime has been created. Send a message first.` (in the VS Code log
`agenthost.log`), and the server shows `Error` in **MCP: List Servers**.

1. Open Chat, switch to **Agent** mode, and send a message such as `Call metronix_status`.
   VS Code starts the server when a chat message is submitted. (Or run **MCP: List Servers**,
   select `metronix`, and start it after the first message. VS Code shows a trust dialog the first
   time a server starts or its configuration changes.)
2. Ask Copilot Chat to call `metronix_memory_store` (`agent_id` `my-agent`, `workspace_id`
   `MTRNIX`, any text), then `metronix_memory_search` for it.

## What was verified

| Item | How |
| --- | --- |
| VS Code with the configuration above | **Run.** VS Code 1.140.0 on macOS, user-level `mcp.json` with the key in `headers`, a regular Copilot Chat in Agent mode. `metronix_status`, `metronix_memory_store` and `metronix_memory_search` worked. Against a stack built from `fix/docker-deps-lock` (URL `http://localhost:18000/mcp`, an isolated stack with a shifted port) |
| Server accepts `url`, `Authorization: Bearer mtk_…` and `X-Agent-Id` exactly as configured above | **Run.** `initialize`, `tools/list`, `metronix_memory_store`, `metronix_memory_search`, `metronix_memory_list` with those headers |
| Shared key cannot use `metronix_memory_*` | **Run.** `AUTH_REQUIRED` |
| A key with a trailing space | **Run.** `401 Invalid or missing MCP API key` |
| Starting the server from a Copilot CLI / Agent Host session | **Run, fails.** See Verify |
| `${input:…}` in `headers` | **Not verified** (see Configuration) |
| `.vscode/mcp.json` layout (`servers`, `type: http`, `headers`), user-config command | **Documentation only**: [VS Code MCP servers](https://code.visualstudio.com/docs/copilot/customization/mcp-servers) and the [MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration) |

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`).

**`Error` status, and `startMcpServer failed … Send a message first` in `agenthost.log`:** You started the server from a Copilot CLI / Agent Host session. Use the regular Chat in Agent mode and send a message.

**"Authenticating to 'localhost:8000'…" and a browser tab with `{"detail":"Not Found"}` (an `/authorize?client_id=…` URL):** The key was not accepted. Metronix has no OAuth endpoints. VS Code got `401` on `/mcp`, found no OAuth metadata (`/.well-known/*` and `/register` return 404), and fell back to its OAuth sign-in. In the VS Code log (**MCP: List Servers** → `metronix` → **Show Output**) you see `Received 401 status with Authorization header, retrying with new auth registration`; in the server log, `POST /mcp 401` followed by 404s. Cancel the sign-in, then check the key: it must be a current `mtk_` key and **must not end with a space or a newline**. Test it outside VS Code with `curl -X POST http://localhost:8000/mcp -H "Authorization: Bearer $MTK" -H 'X-Agent-Id: my-agent' -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`; it must return 200. Do not paste a key into the OAuth client-id prompt.

**HTTP 401 from `/mcp`:** The Bearer value is missing, wrong, revoked, or has a trailing space or newline.

**`AUTH_REQUIRED` from `metronix_memory_*`:** You are using the shared `METRONIX_MCP_API_KEY`. Switch to a personal `mtk_` key.

**`INVALID_PARAMS: X-Agent-Id must match the agent_id tool argument`:** `agent_id` in the tool arguments must equal the `X-Agent-Id` header.
