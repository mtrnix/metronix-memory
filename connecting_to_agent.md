# Connecting an Agent

Metronix exposes an MCP server at `/mcp`. Connecting an agent does two things: it registers
Metronix as an MCP server in the agent's runtime (giving it Metronix's knowledge search and
memory tools), and it tells the agent to use Metronix as its durable-memory store.

There are two ways to do this:

- **[Prompt-based setup](#prompt-based-setup)** — paste a few prompts into the agent and let
  it configure itself. Fastest path; recommended for most users.
- **[Manual setup](#manual-setup)** — register the MCP connection by hand, with no LLM
  involved. Use this when you want a deterministic, reviewable procedure or your runtime is
  not agent-driven. To then make Metronix the agent's primary memory store and migrate
  existing memory, use the prompt-based setup.

Both paths produce the same result. Do this **after** the backend is running and
`METRONIX_MCP_API_KEY` is set in `.env` (see [`install.md`](install.md)).

## What you need

Either path uses the same four values. Give them to the agent, or have them ready before you
edit config by hand.

| Value | Example | Where to get it |
|---|---|---|
| `METRONIX_URL` | `http://localhost:8000/mcp` | Your MCP endpoint. |
| `METRONIX_MCP_API_KEY` | token from `.env` | `METRONIX_MCP_API_KEY` in the server `.env`. Sent as `Authorization: Bearer ...`; `/mcp` returns 401 without it. |
| `AGENT_UUID` | `my-agent-001` | Any stable, unique id you choose, or the `id` returned by `POST /api/v1/agents`. |
| `DEFAULT_WORKSPACE_ID` | `MTRNIX` | The Workspaces UI, or `GET /api/v1/workspaces`. Defaults to `MTRNIX`. |

> **Restart matters.** Most runtimes load MCP servers only at startup. After you register
> the MCP server (either path), restart the agent runtime so the `metronix_*` tools become
> available in the next session.

## Runtime-specific guides

Both setup paths register an MCP server, but **where** that configuration lives differs per
runtime (config file location and format). If you use one of these runtimes, its guide gives
the concrete paths — use it alongside whichever path you choose below:

- **Hermes** — [`docs/integrations/hermes.md`](docs/integrations/hermes.md)
- **Cursor** — [`docs/integrations/cursor.md`](docs/integrations/cursor.md)
- **Claude Desktop** — [`docs/integrations/claude-desktop.md`](docs/integrations/claude-desktop.md)
- **LibreChat** — [`docs/integrations/librechat.md`](docs/integrations/librechat.md)
- **OpenClaw** — [`docs/integrations/openclaw.md`](docs/integrations/openclaw.md)
- **Open WebUI** — [`docs/integrations/openwebui.md`](docs/integrations/openwebui.md)

For any other MCP client, the connection details below are runtime-neutral.

---

## Prompt-based setup

Setup is **three prompts** you paste into your agent, in order. The full text of each prompt
lives on a dedicated page: **[`prompts.md`](prompts.md)**.

1. **Prompt 1 — Install Metronix as an MCP server.** Registers Metronix and exposes its
   knowledge search (RAG) and memory tools. Memory use is optional at this stage. **Restart
   the runtime afterward.**
2. **Prompt 2 — Make Metronix the primary and only memory store.** Flips durable memory from
   optional to mandatory.
3. **Prompt 3 — Migrate existing memory.** Run only if the agent already holds durable
   memory.

Run Prompt 1 in the first session, restart, then run Prompts 2 and 3 in the next session.
See [`prompts.md`](prompts.md) for the prompts, parameters, and exact ordering. For where the
MCP server config lives in your client, see [Runtime-specific guides](#runtime-specific-guides).

---

## Manual setup

Register Metronix as an MCP server by hand — the deterministic, no-LLM equivalent of Prompt 1.
This gives the agent Metronix's knowledge-search and memory tools. To then make Metronix the
agent's primary memory store and migrate existing memory, use the
[prompt-based setup](#prompt-based-setup) (Prompts 2 and 3).

Add Metronix as an MCP server in your runtime's configuration file. Every runtime needs the
same connection details:

- **URL:** `{{METRONIX_URL}}` (e.g. `http://localhost:8000/mcp`)
- **Header:** `Authorization: Bearer {{METRONIX_MCP_API_KEY}}` — required; `/mcp` returns
  401 without it.
- **Header:** `X-Agent-Id: {{AGENT_UUID}}` — required for agent-scoped memory and
  observability. Use the same `AGENT_UUID` in memory tool arguments.
- **Timeout:** 180 seconds. **Connect timeout:** 60 seconds.

Most MCP clients use an `mcpServers` JSON block. The Metronix entry looks like this — adapt
the key names to your client if it differs:

```json
{
  "mcpServers": {
    "metronix": {
      "url": "http://localhost:8000/mcp", # or your METRONIX_MCP_URL
      "headers": {
        "Authorization": "Bearer <METRONIX_MCP_API_KEY>",
        "X-Agent-Id": "<AGENT_UUID>"
      }
    }
  }
}
```

Hermes and other YAML-based clients use the same fields:

```yaml
mcp_servers:
  metronix:
    url: http://localhost:8000/mcp # or your METRONIX_MCP_URL
    headers:
      Authorization: Bearer <METRONIX_MCP_API_KEY>
      X-Agent-Id: <AGENT_UUID>
    timeout: 180
    connect_timeout: 60
```

#### Where the files live

The MCP config file differs per runtime. The always-on / persona file is where the
prompt-based setup records the memory policy, listed here for reference. Common default
locations — confirm exact, version-specific paths in the
[runtime-specific guides](#runtime-specific-guides):

| Runtime | MCP server config file | Always-on / persona file |
|---|---|---|
| **Cursor** | `~/.cursor/mcp.json` (global) or `<project>/.cursor/mcp.json` | `<project>/.cursor/rules/*.mdc` |
| **Claude Desktop** | macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows: `%APPDATA%\Claude\claude_desktop_config.json` | No per-turn system file — use your own long-lived instruction store |
| **Hermes** | `~/.hermes/config.yaml` (YAML) | `~/.hermes/SOUL.md` (or `/root/.hermes/SOUL.md` when running as root) |
| **LibreChat** | `librechat.yaml` (`mcpServers:`) | Agent / custom instructions |
| **OpenClaw** | see [`docs/integrations/openclaw.md`](docs/integrations/openclaw.md) | see its guide |
| **Open WebUI** | Connects to Metronix as an OpenAI-compatible backend, not an MCP client — see [`docs/integrations/openwebui.md`](docs/integrations/openwebui.md) | n/a |

**Restart the agent runtime** so the `metronix_*` tools load.


## Memory kinds

Metronix classifies durable memory by `kind`:

- `fact` (default) — durable factual statements.
- `preference` — stable user or team preferences; auto-injected into context.
- `pinned` — explicit must-remember instructions.

See [`docs/guides/memory.md`](docs/guides/memory.md) for the full memory model, freshness
lifecycle, and access paths.
