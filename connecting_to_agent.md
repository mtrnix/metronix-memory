# Connecting an Agent

> **Authentication mode:** The local setup and generated examples below use
> `METRONIX_MCP_API_KEY` with `AUTH_ENABLED=false`. For a hosted deployment with
> `AUTH_ENABLED=true`, put a user JWT in the same Bearer header; the shared key is ignored.

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

Both paths produce the same result. For the local mode shown below, do this **after** the
backend is running and `METRONIX_MCP_API_KEY` is set in `.env` (see
[`install.md`](install.md)). Hosted users need a JWT from their Metronix administrator.

## What you need

Either path uses the same four values. Give them to the agent, or have them ready before you
edit config by hand.

| Value | Example | Where to get it |
|---|---|---|
| `METRONIX_URL` | `http://localhost:8000/mcp` | MCP endpoint on the host (default). Same service as the **`metronix-full-api`** container (`metronix-core` in Compose), port **8000**, path **`/mcp`**. From inside Docker: `http://metronix-core:8000/mcp`. See [`docs/MCP_API.md`](docs/MCP_API.md). |
| `METRONIX_MCP_API_KEY` | token from `.env` | `METRONIX_MCP_API_KEY` in the server `.env`. Sent as `Authorization: Bearer ...`; `/mcp` returns 401 without it. |
| `AGENT_UUID` | `my-agent-001` | Stable id for this agent: sent as `X-Agent-Id` on MCP and as `agent_id` in memory tools so Metronix attributes requests to the right agent. Must match the agent UUID in **Metronix Console** (corporate version) when linking a runtime there. Create via `POST /api/v1/agents`, the UI, or choose any stable id of 1–64 chars from `A–Z a–z 0–9 . _ -` (UUID or slug). |

### Agent UUID

The agent id is not decorative — Metronix uses it to scope every MCP call:

- **`X-Agent-Id` header** — identifies which agent is connected over MCP; required for
  agent-scoped memory and observability.
- **`agent_id` in tool arguments** — must match the header so store/search/list operations
  hit the same agent's memory partition.
- **Metronix Console (corporate version)** — when you attach Hermes, Cursor, or another
  runtime to an agent in Console, use the same UUID here. Otherwise memory and activity will
  not show up under that agent.

**Format:** 1–64 characters from `A–Z a–z 0–9 . _ -` (UUIDs with or without dashes, or slugs
like `my-agent-001`). Spaces, `/`, and other characters are rejected on the header, in memory
tools, and at `POST /api/v1/agents`. Because the same rule applies everywhere, an id an agent
self-assigns over MCP can later be registered verbatim — its existing memory and activity then
appear under the registered agent.

See [`docs/guides/agents-and-workspaces.md`](docs/guides/agents-and-workspaces.md) for details.
| `DEFAULT_WORKSPACE_ID` | `MTRNIX` | The Workspaces UI, or `GET /api/v1/workspaces`. Defaults to `MTRNIX`. |

> **Restart matters.** Most runtimes load MCP servers only at startup. After you register
> the MCP server (either path), restart the agent runtime so the `metronix_*` tools become
> available in the next session.

## Runtime-specific guides

Both setup paths register an MCP server, but **where** that configuration lives differs per
runtime (config file location and format). If you use one of these runtimes, its guide gives
the concrete paths — use it alongside whichever path you choose below:

- **Hermes** — [`docs/integrations/hermes.md`](docs/integrations/hermes.md) — requires
  `file`, `terminal`, and `code_execution` toolsets for prompt-based setup (enabled by
  default after Hermes *Full Setup*)
- **Claude Code** — [`docs/integrations/claude-code.md`](docs/integrations/claude-code.md) —
  auto-connectable via `./install.sh --connect-claude` (runs `claude mcp add`); has shell access,
  so prompt-based setup works directly
- **Codex** — [`docs/integrations/codex.md`](docs/integrations/codex.md) —
  auto-connectable via `./install.sh --connect-codex` (edits `config.toml` directly, since
  `codex mcp add` can't set the required `X-Agent-Id` header); has shell/file access, so
  prompt-based setup works directly
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

> **Hermes users:** before pasting the prompts, confirm Hermes has `file`, `terminal`, and
> `code_execution` toolsets enabled (default after *Full Setup*). See
> [`docs/integrations/hermes.md`](docs/integrations/hermes.md#prerequisites-hermes-tool-permissions).

---

## Manual setup

Register Metronix as an MCP server by hand — the deterministic, no-LLM equivalent of Prompt 1.
This gives the agent Metronix's knowledge-search and memory tools. To then make Metronix the
agent's primary memory store and migrate existing memory, use the
[prompt-based setup](#prompt-based-setup) (Prompts 2 and 3).

Add Metronix as an MCP server in your runtime's configuration file. Every runtime needs the
same connection details:

- **URL:** `{{METRONIX_URL}}` (default value: `http://localhost:8000/mcp`)
- **Header:** `Authorization: Bearer {{METRONIX_MCP_API_KEY}}` — required; `/mcp` returns
  401 without it.
- **Header:** `X-Agent-Id: {{AGENT_UUID}}` — identifies the agent for MCP and memory;
  use the same value in memory tool arguments and as the agent UUID in Metronix Console
  (corporate version) when linking a runtime there.
- **Timeout:** 180 seconds. **Connect timeout:** 60 seconds.

Most MCP clients use an `mcpServers` JSON block. The Metronix entry looks like this — adapt
the key names to your client if it differs:

```json
{
  "mcpServers": {
    "metronix": {
      "url": "http://localhost:8000/mcp", # default; metronix-full-api container (metronix-core:8000/mcp from Docker)
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
    url: http://localhost:8000/mcp # default; metronix-full-api container (metronix-core:8000/mcp from Docker)
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
| **Claude Code** | `~/.claude.json` (`--scope user`, default) or `<project>/.mcp.json` (`--scope project`/`local`); managed via `claude mcp add` | `~/.claude/CLAUDE.md` (user scope) or `<project>/CLAUDE.md` (project/local scope) |
| **Codex** | `~/.codex/config.toml` (user scope, default) or `<project>/.codex/config.toml` (project scope, requires the project be "trusted"); edited directly, not via `codex mcp add` | `~/.codex/AGENTS.md` (user scope) or `<project>/AGENTS.md` (project scope) |
| **Hermes** | `~/.hermes/config.yaml` (YAML) | `~/.hermes/SOUL.md` (or `/root/.hermes/SOUL.md` when running as root) |
| **LibreChat** | `librechat.yaml` (`mcpServers:`) | Agent / custom instructions |
| **OpenClaw** | `~/.openclaw/openclaw.json` (JSON5) — see [`docs/integrations/openclaw.md`](docs/integrations/openclaw.md) | `~/.openclaw/workspace/SOUL.md` |
| **Open WebUI** | Connects to Metronix as an OpenAI-compatible backend, not an MCP client — see [`docs/integrations/openwebui.md`](docs/integrations/openwebui.md) | n/a |

**Restart the agent runtime** so the `metronix_*` tools load.


## Memory kinds

Metronix classifies durable memory by `kind`:

- `fact` (default) — durable factual statements.
- `preference` — stable user or team preferences; auto-injected into context.
- `pinned` — explicit must-remember instructions.

See [`docs/guides/memory.md`](docs/guides/memory.md) for the full memory model, freshness
lifecycle, and access paths.
