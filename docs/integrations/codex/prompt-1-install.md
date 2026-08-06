# Metronix MCP — install as an MCP server
Authentication mode: this generated prompt targets local `AUTH_ENABLED=false` and uses
`METRONIX_MCP_API_KEY`. For hosted `AUTH_ENABLED=true`, use a user JWT in the Bearer header;
the shared key is ignored.

You are a Codex instance with shell and file access. Run this ONCE per
deployment. If a `[mcp_servers.metronix]` table already exists in your
`config.toml` with the correct URL, just verify it and report — do not create
a duplicate.

## Parameters
- METRONIX_URL = {{METRONIX_URL}}
- METRONIX_MCP_API_KEY  = {{METRONIX_MCP_API_KEY}}
- AGENT_UUID   = {{AGENT_UUID}}
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}

## 0. Check parameters first
If any value above is still a {{...}} placeholder or empty, STOP and try to find those values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- METRONIX_URL — Metronix MCP endpoint URL: server URL + /mcp. If Codex runs in
  WSL2/Docker and Metronix is on the Windows host, use host.docker.internal
  instead of localhost. Example: http://host.docker.internal:8000/mcp
- METRONIX_MCP_API_KEY — Bearer token for /mcp (server env var METRONIX_MCP_API_KEY; /mcp
  returns HTTP 401 without it; ask the Metronix admin if you don't have it).
  Example: the token from the Metronix deployment's .env
- AGENT_UUID — any stable unique id for this agent, provided by the user; the user
  can simply make one up, or create it via POST /api/v1/agents / the UI. You do NOT
  create it. Example: a3c98413c3684a0992ac0e007b93f410
- DEFAULT_WORKSPACE_ID — workspace identifier (Workspaces UI, or GET /api/v1/workspaces).
  Every metronix_* call (search/RAG and memory) needs it, which is why it is set
  now. Example: MTRNIX
Do NOT call POST /api/v1/agents (or otherwise hit the /api/v1/agents endpoint)
yourself to create an agent or obtain AGENT_UUID — registering the agent and its id
is the user's job, done out of band. If AGENT_UUID is missing, ask the user and
wait; never self-register.
Wait for the user's answers and fill them in before continuing.

## 1. Register Metronix as an MCP server
Edit the config.toml yourself (`~/.codex/config.toml` for a machine-wide
registration, or `<project>/.codex/config.toml` for this project only — ask
the user which they want if it isn't obvious; project scope also requires the
project be marked "trusted" in Codex, which is the user's job, not yours).

There is no `codex mcp add ...` command to run for this: the CLI's `mcp add`
only supports `--url` and `--bearer-token-env-var` (plus OAuth flags) — it has
no way to set a custom header, and Metronix requires `X-Agent-Id` in addition
to `Authorization`. So edit the file directly instead.

If `mcp_servers.metronix` is missing, APPEND this table at the end of the
file (do NOT touch any other `[mcp_servers.*]` tables already present):

    [mcp_servers.metronix]
    url = "{{METRONIX_URL}}"
    http_headers = { "Authorization" = "Bearer {{METRONIX_MCP_API_KEY}}", "X-Agent-Id" = "{{AGENT_UUID}}" }
    startup_timeout_sec = 10.0
    tool_timeout_sec = 60.0

The `Authorization` header is REQUIRED — the /mcp endpoint validates
METRONIX_MCP_API_KEY; without it every request is rejected with HTTP 401.
The `X-Agent-Id` header is REQUIRED too — without it, server-side observability
events for search and other no-agent_id-arg tools are dropped silently.

After editing, confirm the file is still valid TOML (re-read it, or run it
through any TOML parser you have available) before moving on — a syntax
mistake here breaks Codex's config entirely, not just the Metronix entry.

## 2. Test, then restart
Run `codex mcp list` from a shell to confirm `metronix` shows up (it will read
back whatever you just wrote, regardless of how it was added). If it errors
or metronix is missing, fix config.toml and retry before continuing.
Then restart: Codex loads MCP servers only at startup, so the metronix_*
tools become available only in the NEXT session.

## Report format
- MCP registration: ok / changes made
- Config file edited: <path>, scope used: user / project
- codex mcp list: metronix present / missing (error)
- Next step: restart the session, then run prompt 2 (memory source)
