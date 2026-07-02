# Metronix MCP — primary & only memory source
You are a Claude Code instance with the Metronix MCP server registered and
active (run prompt 1 first, then restart). Run this ONCE.
Prompt 1 left no memory-policy record; this prompt creates it with mandatory
wording. If a `metronix-config` block already exists with the mandatory
wording, just verify and report.

## Parameters
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}
- AGENT_UUID   = {{AGENT_UUID}}

## 0. Check parameters first
If either value above is still a {{...}} placeholder or empty STOP and try to find those values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- DEFAULT_WORKSPACE_ID — workspace identifier (Workspaces UI, or GET /api/v1/workspaces).
  Example: MTRNIX
- AGENT_UUID — any stable unique id for this agent, provided by the user; the user
  can make one up, or create it via POST /api/v1/agents / the UI. You do NOT create
  it. Example: a3c98413c3684a0992ac0e007b93f410
Wait for the user's answers before continuing.

## 1. Memory policy
From now on, use Metronix memory as the durable knowledge store: all durable
knowledge lives in Metronix, NOT in ad-hoc local notes.
- The routing rule lives in `CLAUDE.md` (step 3 below writes it), which Claude
  Code loads at the start of every session — so you go straight to Metronix
  with no extra lookup hop.
- Metronix memory is classified by `kind`:
  - kind="fact" — durable factual statements ("user works at Acme")
  - kind="preference" — user preferences ("respond in Russian"). Auto-injected
    into prompts without retrieval — pin anything truly persistent here.
  - kind="pinned" — explicit instructions the user marked must-not-vanish.

## 2. Tools you have on Metronix
Search/document (workspace_id only):
`metronix_search_fast`, `metronix_get`, `metronix_store`,
`metronix_status`, `metronix_sync`.
Memory (workspace_id + agent_id BOTH required):
`metronix_memory_store`, `metronix_memory_search`, `metronix_memory_get_context`,
`metronix_memory_list`, `metronix_memory_update`, `metronix_memory_delete`,
`metronix_memory_batch_store`, `metronix_memory_review_list`,
`metronix_memory_review_resolve`. Run `/tools` for full schemas.
ALWAYS pass workspace_id (and agent_id for memory tools) explicitly — defaults
will not add them for you.

## 3. Write the routing rule (CLAUDE.md)
Pick the file that matches the scope prompt 1 registered the MCP server at:
- `--scope user` → `~/.claude/CLAUDE.md` (create the file/dir if missing)
- `--scope project` or `--scope local` → `./CLAUDE.md` in the project root

Do NOT wipe or rewrite existing content in that file; just APPEND this block at
the END, clearly delimited. If a `metronix-config` block is already there (e.g.
from a previous run), update it in place instead of appending a second copy:

    --- metronix-config ---
    Durable memory lives in Metronix MCP. ALWAYS use the metronix_memory_*
    tools for it, with workspace_id="{{DEFAULT_WORKSPACE_ID}}" and
    agent_id="{{AGENT_UUID}}". Classify by kind:
    fact (default) | preference (auto-injected) | pinned (must-not-vanish).
    Do NOT use local scratch files or notes for new durable knowledge, and do
    NOT silently fall back to them. If Metronix is unreachable, say so to the
    user instead of storing durable knowledge locally.
    --- end metronix-config ---

## 4. Verify
- `metronix_status(workspace_id="{{DEFAULT_WORKSPACE_ID}}")` — KB connectivity
- `metronix_memory_list(workspace_id="{{DEFAULT_WORKSPACE_ID}}",
  agent_id="{{AGENT_UUID}}", limit=5)` — memory channel reachable
- confirm the `metronix-config` block in CLAUDE.md has the mandatory wording
  AND that all pre-existing content in the file is still present and unchanged

## Report format
- CLAUDE.md: routing rule written/upgraded at <path>; existing content preserved
- Verify: status ok, memory channel reachable
- Next step: run prompt 3 if this agent has prior memory to migrate
