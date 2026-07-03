# Memory consolidation into Metronix
You are a Codex instance with the Metronix MCP server registered and
active. Your task is to move ALL durable knowledge you currently hold into
Metronix, so that Metronix becomes the single source of truth for long-lived
memory. Run ONCE. Run this ONLY if you already hold durable memory (e.g. an
auto-memory system, notes files, or a `MEMORY.md`).

## Parameters
- DEFAULT_WORKSPACE_ID = {{DEFAULT_WORKSPACE_ID}}
- AGENT_UUID   = {{AGENT_UUID}}

## 0. Check parameters first
If either value above is still a {{...}} placeholder or empty, STOP and try to find those values in .env
If you couldn't find the values, ask the
user for it before doing anything else — never guess. Show these hints:
- DEFAULT_WORKSPACE_ID — workspace identifier (Workspaces UI, or GET /api/v1/workspaces).
  Example: MTRNIX
- AGENT_UUID — any stable unique id for this agent, provided by the user; the user
  can make one up, or create it via POST /api/v1/agents / the UI. You do NOT create
  it. Example: a3c98413c3684a0992ac0e007b93f410
Wait for the user's answers before continuing.

## 1. Inventory every place you keep durable knowledge
Before storing anything, build a complete list of where your durable memory
currently lives. Do NOT stop at the first or most obvious location. Durable
knowledge can be spread across many surfaces, in different forms. Consider, at
minimum:
  - any auto-memory system's files (e.g. `MEMORY.md` and its linked notes);
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

Do NOT migrate or remove `AGENTS.md` itself, or the durable-memory routing rule
it contains — that is configuration, not knowledge, and must stay where it is.

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
    workspace_id="{{DEFAULT_WORKSPACE_ID}}",
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
  - For memory you own exclusively (your own auto-memory files, private
    notes/scratch files): remove the migrated entry so there is one source of
    truth and nothing drifts. (Do NOT remove `AGENTS.md` or the routing rule
    inside it — that is configuration, see step 1.)
  - For shared or external sources you do NOT own exclusively (a shared
    knowledge base, a team wiki): do NOT delete it. Leave it intact and just
    note in your report that it has been mirrored into Metronix.
From now on, write NEW durable knowledge to Metronix — not back into the old
locations.

## 5. Verify
- metronix_memory_list(workspace_id="{{DEFAULT_WORKSPACE_ID}}",
  agent_id="{{AGENT_UUID}}", limit=10) — your migrated entries are visible.
Check that nothing you inventoried in step 1 was left un-migrated.

## Report format
  - Sources found: <list every memory surface you discovered in step 1>
  - Migrated: N items (X fact / Y preference / Z pinned)
  - Skipped: M items (and why — empty, test data, finished task, duplicate)
  - Retired: which owned sources were cleared vs. which external/shared sources
    were left intact and mirrored
  - Verify: memory_list returned K entries — all inventoried sources accounted for
