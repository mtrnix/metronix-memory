# Pi

## Recommended mode

Use Metatron through MCP via Pi's MCP adapter.

If Pi supports `pi install npm:pi-mcp-adapter`, that is the clean path. The adapter lets Pi
talk to Metatron's HTTP MCP endpoint instead of pretending Metatron is a chat-only provider.

## What you need

- Metatron running locally or remotely
- `METATRON_MCP_API_KEY` from the Metatron `.env`
- a stable Pi agent id
- a workspace id such as `MTRNIX`

## Start Metatron first

Pi cannot connect to an MCP endpoint that does not exist yet, which sounds obvious until
it is midnight and everyone starts blaming JSON.

This repo's bootstrap script installs prerequisites and checks Docker:

```bash
./install/bootstrap.sh
```

Then start Metatron:

```bash
docker compose -f docker-compose.full.yml up -d --build
curl http://localhost:8001/health
```

If health is down, fix that before touching Pi MCP config. Otherwise you are debugging an
empty socket with strong opinions.

## Install the Pi MCP adapter

```bash
pi install npm:pi-mcp-adapter
```

Restart Pi after installation if it only loads adapters at startup.

## Connection values

```text
URL:            http://localhost:8001/mcp
Authorization:  Bearer <METATRON_MCP_API_KEY>
X-Agent-Id:     <stable-pi-agent-id>
Timeout:        180
Connect timeout: 60
```

## Pi config checklist

However Pi exposes MCP adapter configuration, make sure the Metatron entry includes:

- the MCP URL above
- the `Authorization` header
- the `X-Agent-Id` header
- one stable agent id reused across sessions

Do not rotate the Pi agent id casually unless you enjoy debugging a memory system that now
thinks each reboot is a new life form.

## Where Pi reads instructions

Pi has two separate prompt layers:

- `AGENTS.md` for project instructions and working conventions
- `.pi/SYSTEM.md` when you want to replace the default system prompt for this project

Pi's current docs say it loads `AGENTS.md` or `CLAUDE.md` from:

- `~/.pi/agent/AGENTS.md` for global instructions
- parent directories, walking up from the current working directory
- the current directory

Pi also supports:

- `.pi/SYSTEM.md` for project system prompt replacement
- `~/.pi/agent/SYSTEM.md` for global system prompt replacement
- `APPEND_SYSTEM.md` to append instead of replace

Source: [Pi usage docs](https://pi.dev/docs/latest/usage#context-files)

## Example project `.mcp.json`

Pi's MCP setup UI shows that it can import project `.mcp.json` files. A reasonable
Metatron config to try is:

```json
{
  "mcpServers": {
    "metatron": {
      "url": "http://localhost:8001/mcp",
      "headers": {
        "Authorization": "Bearer <METATRON_MCP_API_KEY>",
        "X-Agent-Id": "<stable-pi-agent-id>"
      },
      "timeout": 180,
      "connect_timeout": 60
    }
  }
}
```

If Pi rejects `url` or `headers`, use the adapter-managed import path from `/mcp setup` and
let Pi write its compatibility layer. Pi is the one holding the map there.

## Prompt to paste into Pi

```text
You are configuring Pi to use Metatron Core over MCP through Pi's MCP adapter.

Run setup once. If Pi already has a working Metatron MCP configuration, verify it and report
the result instead of creating a duplicate entry.

If the MCP adapter is not installed, install it first with:

pi install npm:pi-mcp-adapter

Ask the user for any missing values:

- METATRON_URL: Metatron MCP endpoint, for example http://localhost:8001/mcp
- METATRON_MCP_API_KEY: token from the Metatron .env file
- AGENT_UUID: stable unique id for this Pi agent
- DEFAULT_WORKSPACE_ID: workspace id, usually MTRNIX for the first install

Configure Pi's MCP adapter to register Metatron with:

- URL: {{METATRON_URL}}
- Header: Authorization: Bearer {{METATRON_MCP_API_KEY}}
- Header: X-Agent-Id: {{AGENT_UUID}}
- Timeout: 180 seconds
- Connect timeout: 60 seconds

The Authorization header is required. The Metatron /mcp endpoint rejects requests without
the configured METATRON_MCP_API_KEY.

The X-Agent-Id header is required for agent-scoped memory and observability. Use the same
AGENT_UUID in memory tool arguments.

After registration, restart Pi if adapters or MCP servers are loaded only at startup.

When tools are available, verify:

1. Call metatron_status with workspace_id="{{DEFAULT_WORKSPACE_ID}}".
2. Call metatron_memory_list with workspace_id="{{DEFAULT_WORKSPACE_ID}}",
   agent_id="{{AGENT_UUID}}", limit=5.
3. If Pi has existing durable memory in its built-in memory store, migrate non-stale entries
   into Metatron:
   - user preferences -> kind="preference"
   - factual durable statements -> kind="fact"
   - explicit always-remember instructions -> kind="pinned"
   Use metatron_memory_store or metatron_memory_batch_store.
4. Keep only a small configuration rule in built-in memory:
   "Durable memory lives in Metatron MCP. Use workspace_id={{DEFAULT_WORKSPACE_ID}}
   and agent_id={{AGENT_UUID}}. Do not silently fall back to built-in durable memory
   if Metatron is unreachable."

Report back in four lines:

- MCP adapter: installed / already present
- MCP registration: ok / changes made
- Verification: metatron_status ok / failed with error
- Memory: memory_list returned N records
```

## Example `AGENTS.md`

Use `AGENTS.md` for project-local working rules and for reminding Pi how Metatron should be
used during normal work.

```md
# Project Instructions

Use Metatron as the durable memory and retrieval backend for this project.

## MCP rules

- Prefer the `metatron` MCP server for durable memory and explicit retrieval.
- Use `workspace_id="MTRNIX"` unless the user specifies another workspace.
- Use `agent_id="<stable-pi-agent-id>"` consistently across sessions.
- Do not silently fall back to built-in durable memory if Metatron is unreachable.

## Verification rules

- Before claiming Metatron is configured, call `metatron_status`.
- When memory behavior matters, verify with `metatron_memory_list` or `metatron_memory_search`.

## Working style

- Keep answers concise by default.
- Surface uncertainty explicitly.
- Prefer inspecting repo files before making assumptions.
```

## Example `.pi/SYSTEM.md`

Use `.pi/SYSTEM.md` only if you want Pi's project system prompt to explicitly encode the
Metatron workflow. This replaces the default project system prompt layer, so keep it tight.

```md
You are Pi operating in this repository with Metatron as the external MCP memory and
retrieval backend.

Behavior rules:

- Treat Metatron as the source of truth for durable memory and shared knowledge.
- Use the configured `metatron` MCP server for search, memory inspection, and memory writes.
- Use `workspace_id="MTRNIX"` unless the user specifies another workspace.
- Use the stable configured Pi agent id consistently.
- If Metatron is unavailable, say so plainly instead of pretending memory succeeded.
- Verify important claims with Metatron tools when possible.

When configuring the environment:

- Check that `http://localhost:8001/health` responds before debugging MCP settings.
- Check that the MCP endpoint is `http://localhost:8001/mcp`.
- Ensure the `Authorization` and `X-Agent-Id` headers are present.
```

If you want to keep Pi's default system prompt and merely add the Metatron policy, use
`APPEND_SYSTEM.md` instead of `.pi/SYSTEM.md`.

## OpenAI-compatible fallback

If Pi cannot use MCP cleanly even with the adapter, use the OpenAI-compatible endpoint:

```text
Base URL: http://localhost:8001/v1
Model:    metatron-rag-<workspace_id>
Key:      <METATRON_OPENAI_COMPAT_KEY>
```

This works for chat, but MCP is the better fit if you want durable memory, retrieval tools,
and explicit sync operations instead of stuffing everything through one completion endpoint.

## Verify manually

Call:

```text
metatron_status(workspace_id="MTRNIX")
metatron_memory_list(workspace_id="MTRNIX", agent_id="<stable-pi-agent-id>", limit=5)
```

Useful Pi commands after setup:

```text
/mcp
/mcp status
/mcp reconnect
```
