# Hermes Integration

This is the full prompt-driven setup for **Hermes**. For any other MCP client, use the
runtime-neutral guide in [`../../connecting_to_agent.md`](../../connecting_to_agent.md).

Setup is **three prompts** you paste into Hermes, in order:

1. **Install Metronix as an MCP server** (`~/.hermes/config.yaml`) — gives Hermes Metronix's
   knowledge search (RAG) *and* memory tools. After this, Hermes *may* use Metronix memory, but
   isn't required to.
2. **Make Metronix the primary & only durable-memory source** (routing rule in `SOUL.md`) — flips
   durable memory from optional to mandatory: Metronix only.
3. **Migrate existing memory** into Metronix (only if the agent already has prior memory).

Use this after Metronix is running and `METRONIX_MCP_API_KEY` is set in `.env`.

> **Shortcut:** `./install.sh` (or `./install.sh --wire-hermes -y` to re-run just
> this) can perform **Prompt 1** for you — it detects `~/.hermes`, fills in the
> values from your deployment, and edits `config.yaml` + `SOUL.md` after showing a
> diff (backup kept). If `~/.hermes` is absent or `yq` isn't installed, it writes a
> ready-to-paste `metronix-hermes-setup.md` instead. Prompts 2 and 3 below remain
> manual.

## Prerequisites (Hermes tool permissions)

The prompts below ask Hermes to **edit files** (`~/.hermes/config.yaml`, `SOUL.md`),
**run shell commands**, and sometimes **execute code** when migrating memory. Hermes must
have these toolsets enabled for your platform (usually CLI):

| Capability | Hermes toolset | Used for |
|---|---|---|
| File access | `file` | Edit MCP config and `SOUL.md` |
| Running scripts / shell | `terminal` | Verify connectivity, helper commands |
| Code execution | `code_execution` | Prompts 2–3 may use `execute_code` during migration |

**Full Setup** at install time (`hermes setup` → *Full Setup*) enables these on the default
CLI toolset (`hermes-cli`). If you installed an older Hermes build, chose **Blank Slate**, or
disabled tools later, turn them back on before running the prompts:

```bash
hermes tools    # interactive UI — enable file, terminal, code_execution for CLI
/tools list     # in-session check
```

See the [Hermes Tools guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools),
[Toolsets reference](https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference),
[Code execution](https://hermes-agent.nousresearch.com/docs/user-guide/features/code-execution),
and [Quickstart — Full Setup vs Blank Slate](https://hermes-agent.nousresearch.com/docs/getting-started/quickstart).

## Variables

| Variable | Description | Where to get it | Example |
|---|---|---|---|
| `{{METRONIX_URL}}` | Metronix MCP endpoint URL | Default on the host: `http://localhost:8000/mcp` (**`metronix-full-api`** container, path `/mcp`). Server URL + `/mcp`. If Hermes runs in WSL2/Docker and Metronix runs on the Windows host, use `host.docker.internal` instead of `localhost` | `http://host.docker.internal:8000/mcp` |
| `{{MCP_API_KEY}}` | Bearer token for `/mcp` | Server env var `METRONIX_MCP_API_KEY` (from the deployment's `.env` / secrets). Required — `/mcp` returns HTTP 401 without it. Ask the Metronix admin if you don't have it | `<token from the Metronix .env>` |
| `{{AGENT_UUID}}` | Agent UUID in Metronix | Stable id sent as `X-Agent-Id` and `agent_id` so Metronix attributes MCP/memory to this agent; must match the agent UUID in **Metronix Console** (corporate version) when linking Hermes there. Create via `POST /api/v1/agents` or the UI | `a3c98413c3684a0992ac0e007b93f410` |
| `{{WORKSPACE_ID}}` | Workspace identifier | Workspaces UI, or `GET /api/v1/workspaces` | `MTRNIX` |

## How to use

1. Fill in the parameter values at the top of each prompt. Find & Replace works fine. If you
   paste a prompt with placeholders still unfilled, the agent will stop and ask you for the
   missing values (with hints), so you can also just paste as-is and answer its questions.
2. **Session 1 — Prompt 1 (install MCP).** Paste prompt 1, then `/quit` and start a new session
   with `hermes`. Hermes loads its MCP client list once at startup, so the `metronix_*` tools
   appear only **after** this restart.
3. **Session 2 — Prompt 2 (memory source), then Prompt 3 (migration).** With the tools now active,
   paste prompt 2 to write the routing rule, then paste prompt 3 if the agent has prior memory to
   migrate. No further restart is needed between them; the `SOUL.md` rule takes effect from the
   next session onward automatically.

---

## Prompt 1 — Install Metronix as an MCP server

```
# Metronix MCP — install as an MCP server
You are a Hermes Agent instance. Run this ONCE per deployment.
If `mcp_servers.metronix` already exists in your config with the correct URL,
just verify it and report — do not create a duplicate.

## Parameters
- METRONIX_URL = {{METRONIX_URL}}
- MCP_API_KEY  = {{MCP_API_KEY}}
- AGENT_UUID   = {{AGENT_UUID}}
- WORKSPACE_ID = {{WORKSPACE_ID}}

## 0. Check parameters first
If any value above is still a {{...}} placeholder or empty, STOP and try to find thouse values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- METRONIX_URL — Metronix MCP endpoint URL: default on the host
  http://localhost:8000/mcp (**metronix-full-api** container, path /mcp). Server URL + /mcp.
  If Hermes runs in WSL2/Docker and Metronix is on the Windows host, use host.docker.internal
  instead of localhost. Example: http://host.docker.internal:8000/mcp
- MCP_API_KEY — Bearer token for /mcp (server env var METRONIX_MCP_API_KEY; /mcp
  returns HTTP 401 without it; ask the Metronix admin if you don't have it).
  Example: the token from the Metronix deployment's .env
- AGENT_UUID — stable unique id for this agent: X-Agent-Id on MCP and agent_id in memory
  tools so Metronix attributes requests correctly; must match the agent UUID in Metronix
  Console (corporate version) when linking Hermes there. The user can make one up, or create
  it via POST /api/v1/agents / the UI. You do NOT create it. Example: a3c98413c3684a0992ac0e007b93f410
- WORKSPACE_ID — workspace identifier (Workspaces UI, or GET /api/v1/workspaces).
  Every metronix_* call (search/RAG and memory) needs it, which is why it is set
  now. Example: MTRNIX
Do NOT call POST /api/v1/agents (or otherwise hit the /api/v1/agents endpoint)
yourself to create an agent or obtain AGENT_UUID — registering the agent and its id
is the user's job, done out of band. If AGENT_UUID is missing, ask the user and
wait; never self-register.
Wait for the user's answers and fill them in before continuing.

## 1. Register Metronix as an MCP server
Read `~/.hermes/config.yaml`. If section `mcp_servers.metronix` is missing or has
the wrong URL, edit the file and ensure it contains:

    mcp_servers:
      metronix:
        url: {{METRONIX_URL}}
        headers:
          Authorization: "Bearer {{MCP_API_KEY}}"   # required: server returns 401 without it
          X-Agent-Id: {{AGENT_UUID}}
        timeout: 180
        connect_timeout: 60

The `Authorization: Bearer` header is REQUIRED — the /mcp endpoint validates
METRONIX_MCP_API_KEY; without it every request is rejected with HTTP 401.
The `X-Agent-Id` header is REQUIRED too — without it, server-side observability
events for search and other no-agent_id-arg tools are dropped silently.

## 2. Record that Metronix is available (SOUL.md)
Edit the LIVE SOUL.md that Hermes actually loads — typically `/root/.hermes/SOUL.md`
when Hermes runs as root, otherwise `~/.hermes/SOUL.md`. Do NOT edit any backup or
copy (e.g. `SOUL.md.bak`, dated copies, files under a `backups/` dir) — those are
not loaded. Do NOT remove or rewrite existing persona content; just APPEND this
block at the END (clearly delimited). If a `metronix-config` block is already there
(e.g. from a previous run), update it in place instead of appending a second copy:

    --- metronix-config ---
    Metronix MCP is available. workspace_id="{{WORKSPACE_ID}}",
    agent_id="{{AGENT_UUID}}". You MAY use the metronix_* tools — knowledge search /
    RAG and memory. Using Metronix for durable memory is OPTIONAL at this stage;
    it is not yet your required store.
    --- end metronix-config ---

This is what lets Hermes use Metronix after the restart; without these params in an
always-loaded file, the agent would not know which workspace_id / agent_id to pass.
Prompt 2 upgrades this block to make Metronix the ONLY durable-memory store.

## 3. Test, then restart
Run `hermes mcp test metronix` from a shell to confirm the client can negotiate
a session. If it errors, fix and retry before continuing.
Then restart: Hermes loads the MCP client list once at startup, so the metronix_*
tools become available only in the NEXT session. Run /quit, then `hermes` again.

## Report format
- MCP registration: ok / changes made
- Availability note: appended to <SOUL.md path>
- mcp test: passed / failed (error)
- Next step: restart the session, then run prompt 2 (memory source)
```

---

## Prompt 2 — Make Metronix the primary & only memory source

```
# Metronix MCP — primary & only memory source
You are a Hermes Agent with the Metronix MCP server registered and active (run
prompt 1 first, then restart). Run this ONCE.
Prompt 1 left a `metronix-config` block in your SOUL.md with the OPTIONAL wording;
this prompt upgrades it to mandatory. If it already has the mandatory wording, just
verify and report.

## Parameters
- WORKSPACE_ID = {{WORKSPACE_ID}}
- AGENT_UUID   = {{AGENT_UUID}}

## 0. Check parameters first
If either value above is still a {{...}} placeholder or empty STOP and try to find thouse values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- WORKSPACE_ID — workspace identifier (Workspaces UI, or GET /api/v1/workspaces).
  Example: MTRNIX
- AGENT_UUID — stable unique id for this agent: X-Agent-Id on MCP and agent_id in memory
  tools; must match the agent UUID in Metronix Console (corporate version) when linking
  Hermes there. The user can make one up, or create it via POST /api/v1/agents / the UI.
  You do NOT create it. Example: a3c98413c3684a0992ac0e007b93f410
Wait for the user's answers before continuing.

## 1. Memory policy
Until now (after prompt 1) using Metronix memory was optional. This prompt makes it
mandatory: all durable knowledge lives in Metronix, NOT in Hermes' built-in files.
- The routing rule lives in `SOUL.md` (prompt 1 created it; step 3 below upgrades
  it), which Hermes loads on EVERY call — so the agent goes straight to Metronix
  with no extra lookup hop.
- Do NOT wipe or edit `~/.hermes/memories/MEMORY.md` or `USER.md` here. Migrating
  their existing content is a separate prompt (prompt 3).
- Metronix memory is classified by `kind`:
  - kind="fact" — durable factual statements ("user works at Acme")
  - kind="preference" — user preferences ("respond in Russian"). Auto-injected
    into prompts without retrieval — pin anything truly persistent here.
  - kind="pinned" — explicit instructions the user marked must-not-vanish.

## 2. Tools you have on Metronix
Search/document (workspace_id only):
`metronix_search`, `metronix_search_fast`, `metronix_get`, `metronix_store`,
`metronix_status`, `metronix_sync`.
Memory (workspace_id + agent_id BOTH required):
`metronix_memory_store`, `metronix_memory_search`, `metronix_memory_get_context`,
`metronix_memory_list`, `metronix_memory_update`, `metronix_memory_delete`,
`metronix_memory_batch_store`, `metronix_memory_review_list`,
`metronix_memory_review_resolve`. Run `/tools` for full schemas.
ALWAYS pass workspace_id (and agent_id for memory tools) explicitly — defaults
will not add them for you.

## 3. Upgrade the routing rule to mandatory (SOUL.md)
Edit the LIVE SOUL.md that Hermes actually loads — typically
`/root/.hermes/SOUL.md` when Hermes runs as root, otherwise `~/.hermes/SOUL.md`
(expand `~` to the home of the user Hermes runs as). Do NOT edit any backup or
copy of it (e.g. `SOUL.md.bak`, `SOUL.backup`, dated copies, files under a
`backups/` dir) — those are not loaded and editing them does nothing.

Prompt 1 wrote a `metronix-config` block with the OPTIONAL wording. Find that
block and REPLACE its body with the mandatory rule below, leaving the agent's
persona and everything else in the file intact. If the block isn't there (prompt 1
was skipped), APPEND it at the END of the file:

    --- metronix-config ---
    Durable memory lives in Metronix MCP. ALWAYS use the metronix_memory_*
    tools for it, with workspace_id="{{WORKSPACE_ID}}" and
    agent_id="{{AGENT_UUID}}". Classify by kind:
    fact (default) | preference (auto-injected) | pinned (must-not-vanish).
    Do NOT use Hermes' built-in memory files for new durable knowledge, and do
    NOT silently fall back to them. If Metronix is unreachable, say so to the
    user instead of storing durable knowledge locally.
    --- end metronix-config ---

Do NOT touch `~/.hermes/memories/MEMORY.md` or `~/.hermes/memories/USER.md` —
leave their existing content exactly as it is.

## 4. Verify
- `metronix_status(workspace_id="{{WORKSPACE_ID}}")` — KB connectivity
- `metronix_memory_list(workspace_id="{{WORKSPACE_ID}}",
  agent_id="{{AGENT_UUID}}", limit=5)` — memory channel reachable
- confirm the live SOUL.md `metronix-config` block now has the mandatory wording
  AND that all of its pre-existing persona content is still present and unchanged

## Report format
- SOUL.md: routing rule upgraded to mandatory; existing persona preserved
- Verify: status ok, memory channel reachable
- Next step: run prompt 3 if this agent has prior memory to migrate
```

---

## Prompt 3 — Migrate existing memory

Run this **only if the agent already holds durable memory**, in the same post-restart session.

The sources of memory are described abstractly on purpose. A previous run migrated only the
obvious, user-facing notes and silently left behind knowledge the agent kept elsewhere (a separate
knowledge base it had been reading from). An agent rarely keeps everything it knows in one place,
so this prompt treats *completeness of the inventory* — sweeping every place the agent keeps
durable knowledge, not just its native memory — as the primary success criterion.

```
# Memory consolidation into Metronix
You are an agent with the Metronix MCP server registered and active. Your task
is to move ALL durable knowledge you currently hold into Metronix, so that
Metronix becomes the single source of truth for long-lived memory. Run ONCE.

## Parameters
- WORKSPACE_ID = {{WORKSPACE_ID}}
- AGENT_UUID   = {{AGENT_UUID}}

## 0. Check parameters first
If either value above is still a {{...}} placeholder or empty,, STOP and try to find thouse values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- WORKSPACE_ID — workspace identifier (Workspaces UI, or GET /api/v1/workspaces).
  Example: MTRNIX
- AGENT_UUID — stable unique id for this agent: X-Agent-Id on MCP and agent_id in memory
  tools; must match the agent UUID in Metronix Console (corporate version) when linking
  Hermes there. The user can make one up, or create it via POST /api/v1/agents / the UI.
  You do NOT create it. Example: a3c98413c3684a0992ac0e007b93f410
Wait for the user's answers before continuing.

## 1. Inventory every place you keep durable knowledge
Before storing anything, build a complete list of where your durable memory
currently lives. Do NOT stop at the first or most obvious location. Durable
knowledge can be spread across many surfaces, in different forms. Consider, at
minimum:
  - your own native / built-in memory, in whatever form it takes;
  - any local notes, scratch files, or working documents you read from or write to;
  - any external or shared knowledge store you have been treating as a source of
    truth (a separate notes system, a shared knowledge base, a wiki, a document
    collection, etc.);
  - pinned or "always remember" instructions the user has given you;
  - durable facts or preferences carried over from earlier sessions.

The most common failure here is migrating only user-facing notes and leaving
structured or external knowledge behind. Completeness of THIS inventory is the
single most important step — err on the side of including a source rather than
skipping it. List every source you found before moving on.

Do NOT migrate or remove your own persona/identity definition or the durable-
memory routing rule itself — those are configuration, not knowledge, and must
stay where they are.

## 2. Classify each item by `kind`
For every distinct piece of durable knowledge (skip empty entries, test/probe
data, and anything tied to an already-finished task), decide its `kind`:
  - kind="fact"       — a durable factual statement (default).
  - kind="preference" — a user preference or behavioral rule (auto-injected into
                        prompts; put anything that must always shape behavior here).
  - kind="pinned"     — an explicit instruction the user marked must-not-vanish.

## 3. Store everything into Metronix
For each item, call:
  metronix_memory_store(
    workspace_id="{{WORKSPACE_ID}}",
    agent_id="{{AGENT_UUID}}",
    content=<the knowledge, self-contained and readable on its own>,
    scope="per_agent",
    source_type="conversation",
    kind=<fact|preference|pinned>,
    importance_score=0.7,
  )
Use metronix_memory_batch_store when you have more than 5 items.
Always pass BOTH workspace_id and agent_id — defaults will not add them for you.
Do not create duplicates: if the same fact appears in more than one source,
store it once.

## 4. Retire the originals (carefully)
After an item is confirmed stored in Metronix:
  - For memory you own exclusively (your own native memory, your private
    notes/scratch files): remove the migrated entry so there is one source of
    truth and nothing drifts. (Do NOT remove your persona/identity definition
    or the routing rule — those are configuration, see step 1.)
  - For shared or external sources you do NOT own exclusively (a shared
    knowledge base, a team wiki): do NOT delete it. Leave it intact and just
    note in your report that it has been mirrored into Metronix.
From now on, write NEW durable knowledge to Metronix — not back into the old
locations.

## 5. Verify
- metronix_memory_list(workspace_id="{{WORKSPACE_ID}}",
  agent_id="{{AGENT_UUID}}", limit=10) — your migrated entries are visible.
Check that nothing you inventoried in step 1 was left un-migrated.

## Report format
  - Sources found: <list every memory surface you discovered in step 1>
  - Migrated: N items (X fact / Y preference / Z pinned)
  - Skipped: M items (and why — empty, test data, finished task, duplicate)
  - Retired: which owned sources were cleared vs. which external/shared sources
    were left intact and mirrored
  - Verify: memory_list returned K entries — all inventoried sources accounted for
```

---

## What happens after the run

- `~/.hermes/config.yaml` gets a fresh (or updated) `mcp_servers.metronix` section with the
  correct URL, the `Authorization: Bearer` header, and the `X-Agent-Id` header.
- `~/.hermes/SOUL.md` gets a `metronix-config` block (loaded on every call): prompt 1 appends it
  with the OPTIONAL wording, prompt 2 upgrades the same block to mandatory. Existing persona
  content, plus `MEMORY.md` and `USER.md`, are left untouched.
- Running prompt 3 sweeps every place the agent kept durable knowledge — native memory, local
  notes, and any external/shared knowledge store — and migrates it into Metronix with proper
  `kind` classification, duplicates collapsed. Memory the agent owns exclusively is then cleared
  so there is a single source of truth; shared and external sources (and the agent's persona /
  routing rule) are left intact and recorded as mirrored.
- From the next session onward, the agent automatically routes all memory operations to Metronix,
  and every tool call shows up in Metronix's activity log.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `metronix_*` tools not visible after prompt 1 | The MCP server list is loaded once at session startup; the newly added server only appears after a restart | Run `/quit`, then `hermes` again; `/tools` should now list `metronix_*` entries |
| `metronix_status` returns an error | No network connectivity between Hermes and Metronix | From the shell where Hermes runs: `curl -v {{METRONIX_URL}}` — it must respond. Check firewall, URL spelling, and that the server is up |
| `metronix_memory_list` returns 0 entries even though you just stored something | `agent_id` mismatch between store and list calls | Verify every call uses the same `agent_id="{{AGENT_UUID}}"` |
| No `tool.called` events show up in Metronix's activity log | `X-Agent-Id` header or `workspace_id` arg isn't reaching the server | Recheck `~/.hermes/config.yaml` (`mcp_servers.metronix.headers`) and that the `workspace_id` rule is being followed |
| Routing rule edit had no effect | The agent edited a backup/copy of `SOUL.md`, not the live file | Edit the live `SOUL.md` (typically `/root/.hermes/SOUL.md` under root); confirm the path Hermes reads at startup |
| Memory consolidation migrated some entries but missed others | The agent stopped at the most obvious source (e.g. user notes) and never inventoried external/shared knowledge | Re-run prompt 3 and insist on step 1 — it must list *every* memory surface before storing anything |
| Hermes ignores parts of a prompt | Underlying LLM is too weak, or the prompt didn't fully fit context | Use a stronger model (DeepSeek V3, Claude Sonnet, GPT-4o); or feed the three prompts one at a time |
| Prompt fails with "cannot write file" / no config edit | `file`, `terminal`, or `code_execution` toolsets disabled | Run `hermes tools` and enable them for CLI; see [Prerequisites](#prerequisites-hermes-tool-permissions) and [Hermes Tools](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools) |
