# Cursor Integration

> **Which key to use.** With `AUTH_ENABLED=false`, the shared `METRONIX_MCP_API_KEY` opens
> `/mcp` but only `metronix_status` and `metronix_search_fast` work with it; the
> `metronix_memory_*` tools return `AUTH_REQUIRED`. For memory, use a personal `mtk_` API key —
> see [Example in 5 minutes](../../README.md#example-in-5-minutes-store-and-find-a-memory)
> (steps 2–3) for how to create one. For hosted `AUTH_ENABLED=true`, put a user JWT in the same
> Bearer header.

Use Metronix through Cursor's MCP support.

## Configuration

1. Start Metronix and confirm `curl http://localhost:8000/health`.
2. Put the key in the environment Cursor is launched from, so it is not written into the file:

   ```bash
   export METRONIX_KEY=mtk_...        # your personal key
   ```

3. Add this to `~/.cursor/mcp.json` (all projects) or `<project>/.cursor/mcp.json` (one project):

   ```json
   {
     "mcpServers": {
       "metronix": {
         "url": "http://localhost:8000/mcp",
         "headers": {
           "Authorization": "Bearer ${env:METRONIX_KEY}",
           "X-Agent-Id": "my-agent"
         }
       }
     }
   }
   ```

   If you prefer a literal key, replace `${env:METRONIX_KEY}` with the key itself and keep the file
   out of version control.

4. Restart Cursor if MCP servers are loaded only at startup. Remote servers need no `type` field.
5. Verify with `metronix_status`, then `metronix_memory_list` with `agent_id` set to your
   `X-Agent-Id` value and `workspace_id` set to `MTRNIX`.

- `X-Agent-Id` is a stable id you choose: 1–64 characters from `A–Z a–z 0–9 . _ -`. Use the same
  value as `agent_id` in memory tool arguments.
- The URL is the host-published port of the `metronix-core` container. From another container on
  the Compose network use `http://metronix-core:8000/mcp`.

The prompt in `../../connecting_to_agent.md` can be pasted into an agent to perform the
setup interactively.

## What was verified

| Item | How |
| --- | --- |
| Server accepts `url`, `Authorization: Bearer mtk_…` and `X-Agent-Id` exactly as in the JSON above | **Run.** `initialize`, `tools/list`, `metronix_memory_store`, `metronix_memory_search`, `metronix_memory_list` with those headers against a stack built from `131d6b0` |
| The JSON above parses | **Run.** `jq .` |
| `mcpServers` / `url` / `headers` layout, config file locations, no `type` for remote servers, `${env:NAME}` interpolation | **Documentation only**: [Cursor MCP docs](https://cursor.com/docs/context/mcp). Cursor itself was not run |

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`).

**Tools not appearing after registration:** Restart Cursor after adding the MCP server. If you used `${env:METRONIX_KEY}`, make sure Cursor was started from a shell where the variable is set.

**HTTP 401:** The Bearer value is missing or wrong (an unknown `mtk_` key returns 401).

**`AUTH_REQUIRED` from `metronix_memory_*`:** You are using the shared `METRONIX_MCP_API_KEY`. Switch to a personal `mtk_` key.

**`INVALID_PARAMS: X-Agent-Id must match the agent_id tool argument`:** `agent_id` in the tool arguments must equal the `X-Agent-Id` header.
