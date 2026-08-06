# Agent Setup Prompts

> **Authentication mode:** Installer-filled prompts target local `AUTH_ENABLED=false` and
> use `METRONIX_MCP_API_KEY`. For hosted `AUTH_ENABLED=true`, replace that credential with
> a user JWT in the Bearer header; the shared key is ignored.

This page collects every prompt used to connect an agent to Metronix over MCP. Paste them
into your agent or LLM client, in order. Each prompt is self-contained — it asks you for any
missing parameter before doing anything.

For the surrounding workflow (what the prompts do, when to restart, and the by-hand
alternative), see [`connecting_to_agent.md`](connecting_to_agent.md).

## Parameters

Every prompt uses the same four values. Fill in the `{{...}}` placeholders before pasting,
or let the agent ask you for them.

| Value | Example | Where to get it |
|---|---|---|
| `METRONIX_URL` | `http://localhost:8000/mcp` | MCP endpoint (default on host). **`metronix-full-api`** container / `metronix-core:8000` + `/mcp`. Use your public HTTPS URL in production. |
| `METRONIX_MCP_API_KEY` | token from `.env` | `METRONIX_MCP_API_KEY` in the server `.env`. Sent as `Authorization: Bearer ...`; `/mcp` returns 401 without it. |
| `AGENT_UUID` | `my-agent-001` | Stable id for this agent: `X-Agent-Id` on MCP + `agent_id` in memory tools. Must match the agent UUID in **Metronix Console** (corporate version) when linking a runtime. From `POST /api/v1/agents`, the UI, or any stable id of 1–64 chars from `A–Z a–z 0–9 . _ -` (UUID or slug). |
| `DEFAULT_WORKSPACE_ID` | `MTRNIX` | The Workspaces UI, or `GET /api/v1/workspaces`. Defaults to `MTRNIX`. |

## Order and restart

The prompts are designed to run in two sessions, because most runtimes load MCP servers
only at startup:

- **Session 1:** run **Prompt 1**, then **restart the agent runtime** so the `metronix_*`
  tools become available.
- **Session 2:** run **Prompt 2**, then **Prompt 3** if the agent has prior memory to
  migrate. No restart needed between them.

> **Claude Code users:** Claude Code has shell access, so it can apply Prompt 1 itself —
> it runs `claude mcp add` (or edits `~/.claude.json` as a fallback) instead of you doing it
> by hand. `./install.sh --connect-claude` automates this same step outside the agent entirely.
> See [`docs/integrations/claude-code.md`](docs/integrations/claude-code.md) and the
> Claude-Code-specific prompt templates the installer fills into
> `metronix-claude-code-setup/`.

> **Codex users:** Codex also has shell and file access, so it can apply Prompt 1 itself —
> it edits `~/.codex/config.toml` directly (there's no `codex mcp add` equivalent here: that
> CLI command can't set the `X-Agent-Id` header Metronix requires). `./install.sh --connect-codex`
> automates this same step outside the agent entirely. See
> [`docs/integrations/codex.md`](docs/integrations/codex.md) and the Codex-specific prompt
> templates the installer fills into `metronix-codex-setup/`.

---

## Prompt 1 — Install Metronix as an MCP server

Gives the agent Metronix's knowledge search (RAG) and memory tools. After this, the agent
*may* use Metronix memory, but is not yet required to.

```text
You are configuring this agent to use Metronix Core over MCP. Run this once.
If a working Metronix MCP server is already configured, verify it and report the
result instead of creating a duplicate entry.

Parameters:
- METRONIX_URL          = {{METRONIX_URL}}
- METRONIX_MCP_API_KEY  = {{METRONIX_MCP_API_KEY}}
- AGENT_UUID            = {{AGENT_UUID}}
- DEFAULT_WORKSPACE_ID  = {{DEFAULT_WORKSPACE_ID}}

If any value above is still a {{...}} placeholder or empty, STOP and try to find thouse values in .env
If you couldn't find the values, ask the user
for it before doing anything else — never guess. Show these hints:
- METRONIX_URL: Metronix MCP endpoint, default value http://localhost:8000/mcp (default on
  the host; same **`metronix-full-api`** container / `metronix-core:8000` + `/mcp`). Use your
  public HTTPS URL in production.
- METRONIX_MCP_API_KEY: token from the Metronix .env (METRONIX_MCP_API_KEY);
  the /mcp endpoint returns HTTP 401 without it.
- AGENT_UUID: stable unique id for this agent — used as X-Agent-Id on MCP and agent_id in
  memory tools so Metronix attributes requests to the right agent; must match the agent UUID
  in Metronix Console (corporate version) when linking a runtime there. The user can provide
  one, or you may generate one yourself (any stable unique string works). Do NOT call
  POST /api/v1/agents to register an agent; making up an id is fine, registering one via the
  API is not.
- DEFAULT_WORKSPACE_ID: workspace id (Workspaces UI, or GET /api/v1/workspaces),
  default value MTRNIX for the first install. Every metronix_* call (both search/RAG and
  memory) needs it, which is why it is set now.

Do NOT call POST /api/v1/agents (or otherwise hit the /api/v1/agents endpoint)
yourself to register an agent. You MAY generate AGENT_UUID yourself if the user
didn't supply one — any stable id of 1–64 chars from A–Z a–z 0–9 . _ - works (a
UUID is a safe default) — but creating/registering an agent record via the API is
the user's job, done out of band.

1. Register Metronix as an MCP server in this runtime using:
   - URL: {{METRONIX_URL}}
   - Header: Authorization: Bearer {{METRONIX_MCP_API_KEY}}
   - Header: X-Agent-Id: {{AGENT_UUID}}
   - Timeout: 180 seconds
   - Connect timeout: 60 seconds
   The Authorization header is required (the /mcp endpoint rejects requests without
   the configured METRONIX_MCP_API_KEY). The X-Agent-Id header is required for
   agent-scoped memory and observability; use the same AGENT_UUID in memory tool
   arguments.

2. Record that Metronix is available. Many runtimes load a persona / system /
   always-on instruction file at the start of every turn. APPEND the block below to
   that file — do NOT overwrite existing content, and edit the live file the runtime
   actually loads, not a backup or copy. If a `metronix-config` block is already
   present (e.g. from a previous run), update it in place instead of appending a
   second copy. If your runtime has no such file, keep it in whatever long-lived
   instruction store it does have. This is what lets the agent use Metronix after
   the restart; without it, the agent would not know which workspace_id / agent_id
   to pass and could not call any metronix_* tool:

     --- metronix-config ---
     Metronix MCP is available. workspace_id="{{DEFAULT_WORKSPACE_ID}}",
     agent_id="{{AGENT_UUID}}". You MAY use the metronix_* tools — knowledge
     search / RAG and memory. Using Metronix for durable memory is OPTIONAL at this
     stage; it is not yet your required store.
     --- end metronix-config ---

3. Restart the agent runtime — most runtimes load MCP servers only at startup, so
   the new tools appear only in the next session.

Report:
- MCP registration: ok / changes made
- Availability note: written to <file>
- Next step: restart, then run prompt 2 (using Metronix memory is optional until
  then), and prompt 3 if the agent has prior memory to migrate
```

---

## Prompt 2 — Make Metronix the primary and only memory store

Flips durable memory from optional to mandatory: from here on, durable memory lives in
Metronix and nowhere else.

```text
You are an agent with the Metronix MCP server already registered and active. Run
this once to make Metronix your primary and only durable-memory store.

Until now, using Metronix memory has been optional. This step makes Metronix your
PRIMARY and ONLY durable-memory store — from here on, durable memory goes nowhere
else.

Parameters:
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}
- AGENT_UUID           = {{AGENT_UUID}}

If either value above is still a {{...}} placeholder or empty, STOP and try to find thouse values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- DEFAULT_WORKSPACE_ID: workspace id (Workspaces UI, or GET /api/v1/workspaces),
  default value MTRNIX for the first install.
- AGENT_UUID: stable unique id for this agent — X-Agent-Id on MCP and agent_id in memory
  tools; must match the agent UUID in Metronix Console (corporate version) when linking a
  runtime. The user can provide one, or you may generate one yourself (any stable unique
  string works). Do NOT call POST /api/v1/agents to register an agent; making up an id is
  fine, registering one via the API is not.

1. Memory policy. Durable knowledge lives in Metronix, classified by kind:
   - kind="fact" (default) — durable factual statements.
   - kind="preference" — user preferences / behavioral rules (auto-injected).
   - kind="pinned" — explicit instructions marked must-not-vanish.
   Memory tools require BOTH workspace_id and agent_id in arguments.

2. Upgrade the routing rule from optional to mandatory. Prompt 1 wrote a
   `metronix-config` block (with the OPTIONAL wording) into the persona / system /
   always-on instruction file your runtime loads every turn. Find that block and
   REPLACE its body with the mandatory rule below, leaving everything else in the
   file intact. If the block isn't there (prompt 1 was skipped), append it. Edit the
   live file the runtime actually loads, not a backup or copy:

     --- metronix-config ---
     Durable memory lives in Metronix MCP. ALWAYS use the metronix_memory_* tools,
     with workspace_id="{{DEFAULT_WORKSPACE_ID}}" and agent_id="{{AGENT_UUID}}".
     kind: fact (default) | preference (auto-injected) | pinned (must-not-vanish).
     Do NOT use local/built-in memory for durable knowledge and do NOT silently
     fall back to it. If Metronix is unreachable, say so instead of storing
     durable knowledge locally.
     --- end metronix-config ---

3. Verify:
   - metronix_status(workspace_id="{{DEFAULT_WORKSPACE_ID}}")
   - metronix_memory_list(workspace_id="{{DEFAULT_WORKSPACE_ID}}",
     agent_id="{{AGENT_UUID}}", limit=5)
   - confirm the rule is saved and any pre-existing instructions are intact.

Report:
- Routing rule: upgraded to mandatory (or appended if prompt 1 was skipped)
- Verify: metronix_status ok / failed, memory_list returned N records
- Next step: run prompt 3 if this agent has prior memory to migrate
```

---

## Prompt 3 — Migrate existing memory

Run this **only** if the agent already holds durable memory, in the same post-restart
session as Prompt 2.

```text
You are an agent with the Metronix MCP server registered and active. Move ALL
durable knowledge you currently hold into Metronix, so it becomes the single
source of truth for long-lived memory. Run once.

Parameters:
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}
- AGENT_UUID           = {{AGENT_UUID}}

If either value above is still a {{...}} placeholder or empty, STOP and try to find thouse values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- DEFAULT_WORKSPACE_ID: workspace id (Workspaces UI, or GET /api/v1/workspaces),
  default value MTRNIX for the first install.
- AGENT_UUID: stable unique id for this agent — X-Agent-Id on MCP and agent_id in memory
  tools; must match the agent UUID in Metronix Console (corporate version) when linking a
  runtime. The user can provide one, or you may generate one yourself (any stable unique
  string works). Do NOT call POST /api/v1/agents to register an agent; making up an id is
  fine, registering one via the API is not.

1. Inventory every place you keep durable knowledge. Do NOT stop at the first or
   most obvious location — durable knowledge is often spread across surfaces:
   - your own native / built-in memory, in whatever form it takes;
   - local notes, scratch files, or working documents you read or write;
   - any external or shared knowledge store you treat as a source of truth
     (a separate notes system, a shared knowledge base, a wiki, a doc collection);
   - pinned / "always remember" instructions;
   - durable facts or preferences carried over from earlier sessions.
   The most common failure is migrating only user-facing notes and leaving
   structured or external knowledge behind. Completeness of this inventory is the
   single most important step. List every source before moving on. Do NOT migrate
   or remove your own persona/identity definition or the routing rule itself —
   those are configuration, not knowledge.

2. Classify each item (skip empty entries, test data, finished-task items) by
   kind: fact (default) | preference | pinned.

3. Store each item with:
   metronix_memory_store(workspace_id="{{DEFAULT_WORKSPACE_ID}}",
     agent_id="{{AGENT_UUID}}", content=<self-contained text>, scope="per_agent",
     source_type="conversation", kind=<fact|preference|pinned>,
     importance_score=0.7)
   Use metronix_memory_batch_store for more than 5 items. Always pass BOTH
   workspace_id and agent_id. Do not store duplicates.

4. Retire the originals carefully. For memory you own exclusively (your native
   memory, private notes): remove the migrated entry so there's one source of
   truth (but NOT your persona or the routing rule). For shared or external
   sources you do not own exclusively: do NOT delete them — leave them intact and
   note that they were mirrored. From now on, write new durable knowledge to
   Metronix, not back into the old locations.

5. Verify with metronix_memory_list(workspace_id="{{DEFAULT_WORKSPACE_ID}}",
   agent_id="{{AGENT_UUID}}", limit=10) and confirm nothing inventoried in step 1
   was left un-migrated.

Report:
- Sources found: <every memory surface from step 1>
- Migrated: N items (X fact / Y preference / Z pinned)
- Skipped: M items (and why)
- Retired: which owned sources were cleared vs. external/shared left intact
- Verify: memory_list returned K entries — all inventoried sources accounted for
```

---

## Prompt 4 — Roll back to the state after Prompt 1

Run this to **undo Prompt 2**: flip durable memory from mandatory back to optional, returning
the agent to exactly the state it was in right after Prompt 1. The Metronix MCP server stays
registered and nothing you stored in Metronix (including anything migrated in Prompt 3) is
touched — only the routing-rule wording is reverted.

```text
You are an agent with the Metronix MCP server already registered and active. Run
this once to roll the memory policy back to the state right after Prompt 1: using
Metronix memory becomes OPTIONAL again, instead of your primary and only
durable-memory store.

This reverts ONLY what Prompt 2 changed (the routing-rule wording). It does NOT
remove the Metronix MCP server (that was Prompt 1) and does NOT delete or move any
memory already stored in Metronix, including anything migrated in Prompt 3 — that
data stays exactly where it is.

Parameters:
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}
- AGENT_UUID           = {{AGENT_UUID}}

If either value above is still a {{...}} placeholder or empty, STOP and try to find thouse values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- DEFAULT_WORKSPACE_ID: workspace id (Workspaces UI, or GET /api/v1/workspaces),
  default value MTRNIX for the first install.
- AGENT_UUID: a stable id for this agent — the user can provide one, or you may
  generate one yourself (1–64 chars from A–Z a–z 0–9 . _ -; a UUID is a safe default).
  Do NOT call POST /api/v1/agents to register an agent; making up an id is fine,
  registering one via the API is not.

1. Downgrade the routing rule from mandatory back to optional. Prompt 2 replaced the
   `metronix-config` block with the MANDATORY wording in the persona / system /
   always-on instruction file your runtime loads every turn. Find that block and
   REPLACE its body with the OPTIONAL rule below, leaving everything else in the file
   intact. If the block isn't there, append it. Edit the live file the runtime
   actually loads, not a backup or copy:

     --- metronix-config ---
     Metronix MCP is available. workspace_id="{{DEFAULT_WORKSPACE_ID}}",
     agent_id="{{AGENT_UUID}}". You MAY use the metronix_* tools — knowledge
     search / RAG and memory. Using Metronix for durable memory is OPTIONAL at this
     stage; it is not your required store.
     --- end metronix-config ---

2. Verify:
   - confirm the `metronix-config` block now has the OPTIONAL wording and any
     pre-existing instructions are intact.
   - metronix_status(workspace_id="{{DEFAULT_WORKSPACE_ID}}") still works — the MCP
     server is left in place.

Report:
- Routing rule: downgraded to optional (Prompt 2 reverted)
- Left intact: Metronix MCP server registration, all stored/migrated memory
- Next step: re-run Prompt 2 to make Metronix mandatory again, if desired
```
