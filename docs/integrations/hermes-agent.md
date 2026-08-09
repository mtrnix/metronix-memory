# Hermes Agent

> **MCP authentication mode:** The example targets local `AUTH_ENABLED=false` and uses
> `METRONIX_MCP_API_KEY`. For hosted `AUTH_ENABLED=true`, put a user JWT in the same Bearer
> header; the shared key is ignored.

## Choose an integration

Metronix supports two complementary Hermes integrations:

- **Native memory provider** — use the standalone
  [`hermes-memory-metronix`](https://github.com/mtrnix/hermes-memory-metronix)
  package when Hermes should prefetch durable memory before a turn and route
  `memory(action="add")` through Metronix automatically.
- **HTTP MCP server** — use the MCP configuration below when Hermes needs
  explicit knowledge-base and memory tools such as `metronix_search_fast` and
  `metronix_memory_search`.

You can install both: the native provider handles Hermes's memory lifecycle,
while MCP exposes the broader Metronix tool surface.

## Native memory provider

Install the published package, then run its interactive setup command:

```bash
uv tool install "hermes-memory-metronix>=2026.32.3"
hermes-metronix-setup --generate-token
```

The setup command installs the provider, stores its non-secret settings in
`~/.hermes/metronix.json`, writes the REST credential to `~/.hermes/.env`, and
selects it through `hermes memory setup metronix`.

Verify the provider and its lifecycle with a normal Hermes chat:

```bash
hermes memory status
hermes chat
```

Store a unique fact with Hermes memory, start a fresh chat, and ask for it.
For a recorded end-to-end example, see the
[native Hermes smoke video](https://www.youtube.com/watch?v=Sc6QOyD7Yek).

The native provider calls `/api/v1/*`, so it requires a REST JWT or `mtk_…`
personal API key in `METRONIX_AUTH_TOKEN`. Do **not** use
`METRONIX_MCP_API_KEY`: that credential is only for `/mcp`.

## MCP mode

## What you need

- Metronix Memory running locally or remotely
- an MCP bearer credential: `METRONIX_MCP_API_KEY` from `.env` when
  `AUTH_ENABLED=false`, or a user JWT when `AUTH_ENABLED=true`
- a stable Hermes agent id
- a workspace id such as `MTRNIX`

## Connection values

```text
URL:          http://localhost:8000/mcp
Authorization: Bearer <MCP_API_KEY_OR_JWT>
X-Agent-Id:    <stable-hermes-agent-id>
```

## Example Hermes config

```yaml
mcp_servers:
  metronix:
    url: http://localhost:8000/mcp
    headers:
      Authorization: "Bearer <MCP_API_KEY_OR_JWT>"
      X-Agent-Id: "<AGENT_UUID>"
    timeout: 180
    connect_timeout: 60
```

Restart Hermes after changing MCP configuration.

## Automated setup

`./install.sh --connect-hermes -y` can add the MCP server and an availability
note to `SOUL.md` when it finds an existing Hermes configuration. If the
installer cannot safely edit that configuration, it writes deployment-specific prompts to
`metronix-hermes-setup/` instead. Those generated files contain the MCP key and
are intentionally ignored by Git.

Making Metronix the primary durable-memory source and migrating existing
memories remain deliberate follow-up steps. The prompt-driven path needs the
Hermes `file`, `terminal`, and `code_execution` toolsets; the canonical prompt
templates live in [`hermes/`](hermes/).

## Verify

Call:

```text
metronix_status(workspace_id="MTRNIX")
metronix_memory_list(workspace_id="MTRNIX", agent_id="<AGENT_UUID>", limit=5)
```

## Troubleshooting

**MCP server not responding:** Verify the stack is running (`curl http://localhost:8000/health`). With `AUTH_ENABLED=false`, check that `METRONIX_MCP_API_KEY` in `.env` matches the Hermes config. With `AUTH_ENABLED=true`, use a valid user JWT instead.

**Tools not appearing after registration:** Restart Hermes after changing MCP configuration — it loads MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer` header matches the configured MCP mode: a user JWT for `AUTH_ENABLED=true`, or `METRONIX_MCP_API_KEY` for `AUTH_ENABLED=false`.

## Recommendation

Use the native provider when Hermes should automatically recall and persist
durable memory. Use MCP when the agent should explicitly search Metronix's
knowledge base or call its broader tool surface. Install both when the
workflow needs both capabilities.
