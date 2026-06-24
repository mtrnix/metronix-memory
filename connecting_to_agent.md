# Connecting Metronix To An Agent

Metronix exposes an MCP server at `/mcp`. Setup is **three prompts** you paste into your agent or
LLM client, in order:

1. **Install Metronix as an MCP server** — gives the agent Metronix's knowledge search (RAG) *and*
   memory tools. After this the agent *may* use Metronix memory, but isn't required to.
2. **Make Metronix the agent's primary & only durable-memory store** — flips durable memory from
   optional to mandatory: it must live in Metronix, nowhere else.
3. **Migrate the agent's existing memory** into Metronix (only if it already has prior memory).

Use this after Metronix is running and `METRONIX_MCP_API_KEY` is set in `.env`.

## Agent-specific guides

If you're using one of these agents, follow its dedicated guide instead — it walks the full setup
with that runtime's concrete config paths and file locations:

- **Hermes** — [`docs/integrations/hermes.md`](docs/integrations/hermes.md)

More agents will be added here later. For any other MCP client, use the runtime-neutral prompts
below.

## What The Agent Needs

Give the agent these values, or let it ask you for them:

| Value | Example | Notes |
|---|---|---|
| `METRONIX_URL` | `http://localhost:8000/mcp` | Use your public HTTPS URL in production. |
| `METRONIX_MCP_API_KEY` | token from `.env` | Sent as `Authorization: Bearer ...`. `/mcp` returns 401 without it. |
| `AGENT_UUID` | `my-agent-001` | Any stable unique id, or the `id` returned by `POST /api/v1/agents`. |
| `DEFAULT_WORKSPACE_ID` | `MTRNIX` | Workspaces UI, or `GET /api/v1/workspaces`. |

## Order And Restart

MCP tools usually become available only after a restart, so the order matters:

- **Session 1:** run **prompt 1**, then restart the agent runtime (most runtimes load MCP servers
  only at startup, so the `metronix_*` tools appear only in the next session).
- **Session 2:** with the tools now active, run **prompt 2**, then **prompt 3** if the agent has
  prior memory. No further restart is needed between them.

---

## Prompt 1 — Install Metronix as an MCP server

```text
You are configuring this agent to use Metronix Core over MCP. Run this once.
If a working Metronix MCP server is already configured, verify it and report the
result instead of creating a duplicate entry.

Parameters:
- METRONIX_URL          = {{METRONIX_URL}}
- METRONIX_MCP_API_KEY  = {{METRONIX_MCP_API_KEY}}
- AGENT_UUID            = {{AGENT_UUID}}
- DEFAULT_WORKSPACE_ID  = {{DEFAULT_WORKSPACE_ID}}

If any value above is still a {{...}} placeholder or empty, STOP and ask the user
for it before doing anything else — never guess. Show these hints:
- METRONIX_URL: Metronix MCP endpoint, e.g. http://localhost:8000/mcp (use your
  public HTTPS URL in production).
- METRONIX_MCP_API_KEY: token from the Metronix .env (METRONIX_MCP_API_KEY);
  the /mcp endpoint returns HTTP 401 without it.
- AGENT_UUID: any stable unique id for this agent, provided by the user — the user
  can simply make one up, or create it via POST /api/v1/agents / the UI. Do NOT
  create or register one yourself.
- DEFAULT_WORKSPACE_ID: workspace id (Workspaces UI, or GET /api/v1/workspaces),
  usually MTRNIX for the first install. Every metronix_* call (both search/RAG and
  memory) needs it, which is why it is set now.

Do NOT call POST /api/v1/agents (or otherwise hit the /api/v1/agents endpoint)
yourself to create an agent or obtain AGENT_UUID — registering the agent and its id
is the user's job, done out of band. If AGENT_UUID is missing, ask the user and
wait; never self-register.

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

## Prompt 2 — Make Metronix the primary & only memory source

```text
You are an agent with the Metronix MCP server already registered and active. Run
this once to make Metronix your primary and only durable-memory store.

Until now, using Metronix memory has been optional. This step makes Metronix your
PRIMARY and ONLY durable-memory store — from here on, durable memory goes nowhere
else.

Parameters:
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}
- AGENT_UUID           = {{AGENT_UUID}}

If either value above is still a {{...}} placeholder or empty, STOP and ask the
user for it before doing anything else — never guess. Show these hints:
- DEFAULT_WORKSPACE_ID: workspace id (Workspaces UI, or GET /api/v1/workspaces),
  usually MTRNIX for the first install.
- AGENT_UUID: any stable unique id for this agent, provided by the user — they can
  make one up, or create it via POST /api/v1/agents / the UI. Do NOT create or
  register one yourself.

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

Run this only if the agent already holds durable memory, in the same post-restart session.

```text
You are an agent with the Metronix MCP server registered and active. Move ALL
durable knowledge you currently hold into Metronix, so it becomes the single
source of truth for long-lived memory. Run once.

Parameters:
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}
- AGENT_UUID           = {{AGENT_UUID}}

If either value above is still a {{...}} placeholder or empty, STOP and ask the
user for it before doing anything else — never guess. Show these hints:
- DEFAULT_WORKSPACE_ID: workspace id (Workspaces UI, or GET /api/v1/workspaces),
  usually MTRNIX for the first install.
- AGENT_UUID: any stable unique id for this agent, provided by the user — they can
  make one up, or create it via POST /api/v1/agents / the UI. Do NOT create or
  register one yourself.

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

## Client-Specific Notes

Different MCP clients store server configuration in different places. The neutral prompts above are
runtime-neutral. Use the dedicated integration guides in `docs/integrations/` when you want
manual or runtime-specific setup instructions for a specific client.
