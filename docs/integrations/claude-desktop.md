# Claude Desktop Integration

> **Which key to use.** With `AUTH_ENABLED=false`, the shared `METRONIX_MCP_API_KEY` opens
> `/mcp` but only `metronix_status` and `metronix_search_fast` work with it; the
> `metronix_memory_*` tools return `AUTH_REQUIRED`. For memory, use a personal `mtk_` API key —
> see [Example in 5 minutes](../../README.md#example-in-5-minutes-store-and-find-a-memory)
> (steps 2–3) for how to create one. For hosted `AUTH_ENABLED=true`, put a user JWT in the same
> Bearer header.

Configure Claude Desktop as an MCP client for Metronix.

Claude Desktop's `claude_desktop_config.json` starts local (stdio) servers with `command` and
`args`; it has no `url`/`headers` entry for a remote HTTP server. Metronix is an HTTP server, so
Claude Desktop reaches it through the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote)
bridge, which Claude Desktop launches as a stdio process and which forwards to `/mcp` with your
headers. Node.js (and `npx`) must be installed.

## Configuration

Open **Settings → Developer → Edit Config** (or edit the file directly):

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add the `metronix` server:

```json
{
  "mcpServers": {
    "metronix": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@0.14.3",
        "http://localhost:8000/mcp",
        "--header",
        "Authorization:${METRONIX_AUTH_HEADER}",
        "--header",
        "X-Agent-Id:my-agent"
      ],
      "env": {
        "METRONIX_AUTH_HEADER": "Bearer mtk_..."
      }
    }
  }
}
```

- Replace `mtk_...` with your personal API key. The key lives in `env`, and `--header` refers to
  it as `${METRONIX_AUTH_HEADER}`, so the header value (which contains a space) is not split by
  the command line.
- Write the headers as `Name:value` with no space after the colon.
- `X-Agent-Id` is a stable id you choose: 1–64 characters from `A–Z a–z 0–9 . _ -`. Use the same
  value as `agent_id` in memory tool arguments.
- `mcp-remote` is pinned to `0.14.3`, the version this was tested with. `http://localhost` works
  without `--allow-http`; a plain-HTTP URL on another host needs it.
- The URL is the host-published port of the `metronix-core` container.

Quit and restart Claude Desktop — it loads MCP servers only at startup. Then verify that the
`metronix_*` tools are visible, call `metronix_status` first, then `metronix_memory_list` with
`agent_id` set to your `X-Agent-Id` value and `workspace_id` set to `MTRNIX`.

Use `../../connecting_to_agent.md` when you want an agent to perform the setup steps.

## What was verified

| Item | How |
| --- | --- |
| The bridge works against Metronix with this exact argument shape and `env` indirection | **Run.** `npx -y mcp-remote@0.14.3 http://localhost:8000/mcp --header "Authorization:${METRONIX_AUTH_HEADER}" --header "X-Agent-Id:my-agent"`, with `METRONIX_AUTH_HEADER` set in the environment, driven over stdio: `initialize` (server `MetronixMCP`, protocol `2025-03-26`), `tools/list` (22 tools, includes `metronix_memory_search`), and a `metronix_memory_search` call that returned a stored record. Against a stack built from `131d6b0` |
| The JSON above parses | **Run.** `jq .` |
| Claude Desktop config file locations, `command`/`args`/`env` format, restart requirement, log location | **Documentation only**: [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers). Claude Desktop itself was not run, so loading the bridge from the app is untested |

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`).
Claude Desktop writes MCP logs to `~/Library/Logs/Claude` (macOS) or `%APPDATA%\Claude\logs`
(Windows): `mcp.log` and `mcp-server-metronix.log`.

**Tools not appearing after registration:** Restart Claude Desktop after editing the config. Check
that `npx` is on the `PATH` Claude Desktop sees.

**HTTP 401:** The key in `METRONIX_AUTH_HEADER` is missing or wrong (an unknown `mtk_` key returns
401). The value must start with `Bearer `.

**`AUTH_REQUIRED` from `metronix_memory_*`:** You are using the shared `METRONIX_MCP_API_KEY`. Switch to a personal `mtk_` key.

**`INVALID_PARAMS: X-Agent-Id must match the agent_id tool argument`:** `agent_id` in the tool arguments must equal the `X-Agent-Id` header.
