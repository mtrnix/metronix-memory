# Connecting Metronix Memory To An Agent

Metronix Memory exposes an MCP server at `/mcp`. The easiest setup path is to paste the prompt
below into your agent or LLM client and let it configure the MCP connection.

Use this after Metronix Memory is running and `METATRON_MCP_API_KEY` is set in `.env`.

## What The Agent Needs

Give the agent these values, or let it ask you for them:

| Value | Example | Notes |
|---|---|---|
| `METATRON_URL` | `http://localhost:8001/mcp` | Use your public HTTPS URL in production. |
| `METATRON_MCP_API_KEY` | generated token from `.env` | Sent as `Authorization: Bearer ...`. |
| `AGENT_UUID` | `my-agent-001` | Any stable unique id for this agent. |
| `DEFAULT_WORKSPACE_ID` | `MTRNIX` | Default workspace from `.env.example`. |

## Prompt To Paste Into Your Agent

```text
You are configuring this agent to use Metronix Memory over MCP.

Run the setup once. If you already have a working Metronix Memory MCP server configuration,
verify it and report the result instead of creating a duplicate entry.

Ask the user for any missing values:

- METATRON_URL: Metronix Memory MCP endpoint, for example http://localhost:8001/mcp
- METATRON_MCP_API_KEY: token from the Metronix Memory .env file
- AGENT_UUID: stable unique id for this agent
- DEFAULT_WORKSPACE_ID: workspace id, usually MTRNIX for the first install

Register Metronix Memory as an MCP server in this agent runtime using:

- URL: {{METATRON_URL}}
- Header: Authorization: Bearer {{METATRON_MCP_API_KEY}}
- Header: X-Agent-Id: {{AGENT_UUID}}
- Timeout: 180 seconds
- Connect timeout: 60 seconds

The Authorization header is required. The Metronix Memory /mcp endpoint rejects requests
without the configured METATRON_MCP_API_KEY.

The X-Agent-Id header is required for agent-scoped memory and observability. Use the
same AGENT_UUID in memory tool arguments.

After registration, restart the agent runtime if MCP servers are loaded only at startup.

When tools are available, verify:

1. Call metatron_status with workspace_id="{{DEFAULT_WORKSPACE_ID}}".
2. Call metatron_memory_list with workspace_id="{{DEFAULT_WORKSPACE_ID}}",
   agent_id="{{AGENT_UUID}}", limit=5.
3. If the agent has existing durable memory in its built-in memory store, migrate
   non-stale entries into Metronix Memory:
   - user preferences -> kind="preference"
   - factual durable statements -> kind="fact"
   - explicit always-remember instructions -> kind="pinned"
   Use metatron_memory_store or metatron_memory_batch_store.
4. Keep only a small configuration rule in built-in memory:
   "Durable memory lives in Metronix Memory MCP. Use workspace_id={{DEFAULT_WORKSPACE_ID}}
   and agent_id={{AGENT_UUID}}. Do not silently fall back to built-in durable memory
   if Metronix Memory is unreachable."

Report back in four lines:

- MCP registration: ok / changes made
- Verification: metatron_status ok / failed with error
- Memory: memory_list returned N records
- Built-in memory: migrated / skipped / not applicable
```

## Client-Specific Notes

Different MCP clients store server configuration in different places. The prompt above
is intentionally runtime-neutral. Use the dedicated integration guides in `docs/integrations/`
when you want manual setup instructions for a specific client.
