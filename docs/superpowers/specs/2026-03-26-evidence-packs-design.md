# Structured Evidence Packs — Design Spec

> **Task 6** of the "Investigate and improve search quality" epic.
> Depends on Task 4 (unified reranking with configurable weights).

**Goal:** Replace flat fragment list with structured evidence packs grouped by source role, with explicit PRIMARY/SUPPORTING markers, so the LLM produces better-grounded answers with proper attribution.

**Architecture:** Three changes — (1) connectors declare `source_role`, written into Qdrant payload at ingestion; (2) `_collect_frags()` returns enriched dicts, `_mark_evidence_role()` labels fragments, `_build_ctx()` groups by source role; (3) `HYBRID_SYSTEM_PROMPT` gets atomic evidence rules for citation, uncertainty, and conflict handling.

---

## 1. Source Roles

4 source roles describing the function of a connector:

| source_role | Description | Default connectors |
|---|---|---|
| `task_tracker` | Tasks, statuses, sprints, work items | jira, github |
| `knowledge_base` | Documentation, architecture, processes, wikis | confluence, notion, gdrive |
| `user_upload` | User-uploaded files, reports, PDFs | upload (files connector) |
| `communication` | Conversations, threads, messages | slack_history |

### Where source_role is defined

1. **`ConnectorInterface`** — new property `source_role: str` with default `"knowledge_base"` (safest fallback — most connectors are documentation sources).

2. **Each connector class** — overrides the default:
   - `JiraConnector.source_role = "task_tracker"`
   - `GithubConnector.source_role = "task_tracker"`
   - `SlackHistoryConnector.source_role = "communication"`
   - `FilesConnector.source_role = "user_upload"`
   - `ConfluenceConnector`, `NotionConnector`, `GDriveConnector` — keep default `"knowledge_base"`

3. **Connection record (DB)** — optional `source_role_override` field. If set, takes precedence over the connector class default. Allows admin to override per-connection (e.g., Confluence used as task tracker).

### How source_role reaches fragments

During ingestion (`pipeline.py`), `source_role` is written into the Qdrant chunk payload alongside existing fields (`source_type`, `doc_label`, `title`, `date`). At recall time, each result's metadata already contains `source_role`.

**Reindex required** after deployment — existing chunks lack `source_role` in payload. No backward-compatibility fallback needed (confirmed: dataset is small, full reindex is acceptable).

---

## 2. Evidence Marking

### Profile → primary role mapping

```python
PROFILE_PRIMARY_ROLE: dict[str, str | None] = {
    "execution":     "task_tracker",
    "documentation": "knowledge_base",
    "user_file":     "user_upload",
    "relationship":  "knowledge_base",
    "temporal":      "task_tracker",
    "mixed":         None,  # all SUPPORTING — current behavior
}
```

When `mixed` or classifier disabled → `primary_role = None` → all fragments get `[SUPPORTING]`. This ensures zero behavior change when classifier is off.

### Marking logic

New function `_mark_evidence_role(frags, query_profile)`:

For each fragment:
- If `source_role == primary_role` for current profile → marker = `"PRIMARY"`
- Else → marker = `"SUPPORTING"`
- If `primary_role is None` → all `"SUPPORTING"`

Unknown `source_role` values → `"SUPPORTING"` (safe fallback).

### Fragment text format

```
[PRIMARY] [CONFLUENCE] Architecture Overview (2026-03-20)
The system uses 6 architectural layers...

[SUPPORTING] [JIRA] MTRNIX-104 (2026-03-25)
Implementing auth module, status: in progress
```

Marker is the first token — even small (7B) models can follow "prioritize [PRIMARY]" as simple pattern matching.

---

## 3. Context Assembly (`_build_ctx`)

### Current format (flat)

```
Vector search results (texts):
["[JIRA] MTRNIX-104\ntext...", "[CONFLUENCE] Architecture\ntext...", ...]

Graph entities: [...]
Entity relationships: [...]
Related documents: [...]
```

### New format (grouped)

```
## Task tracker sources
[PRIMARY] [JIRA] MTRNIX-104 (2026-03-25)
Implementing auth module...

[PRIMARY] [JIRA] MTRNIX-99 (2026-03-22)
RBAC integration complete...

## Knowledge base sources
[SUPPORTING] [CONFLUENCE] Architecture Overview (2026-03-20)
The system uses 6 architectural layers...

## Graph context
Entities: [...]
Relationships: [...]
Related documents: [...]
```

### Grouping rules

- Fragments grouped by `source_role`
- PRIMARY group appears first in context
- Remaining groups in fixed order: `knowledge_base`, `task_tracker`, `user_upload`, `communication`
- Empty groups are skipped (no empty sections)
- Graph context remains as-is (already a separate section)

### `_collect_frags()` return type change

Current: `list[str]`
New: `list[dict]` where each dict:

```python
{
    "text": str,          # fragment text (without markers — added later)
    "source_type": str,   # "jira", "confluence", etc.
    "source_role": str,   # "task_tracker", "knowledge_base", etc.
    "title": str,         # document title
    "date": str | None,   # document date if available
    "doc_label": str,     # for FinOps tracking
}
```

Downstream consumers updated: `select_fragments_within_budget()` operates on `frag["text"]`, trace logging adapted.

### Token budget

Total context size does not increase meaningfully. Section headers (`## Task tracker sources` etc.) + dates add ~30-50 tokens. With a budget of 6000-8000 tokens, this is <1%.

---

## 4. System Prompt Update

Add to `HYBRID_SYSTEM_PROMPT` after existing "Your task" section:

```
## Evidence rules
- Fragments marked [PRIMARY] are the most relevant sources. Prioritize them.
- Fragments marked [SUPPORTING] provide additional context. Use to corroborate.
- When stating a fact, cite the source: "according to [JIRA] MTRNIX-104..."
  or "per [CONFLUENCE] Architecture Overview..."
- If a fact appears in only one source, note this: "(based on [SOURCE] only)"
- If sources contradict each other, state both versions with their sources.
- If the context is insufficient to answer, say so directly. Do not guess.
- Never mix facts from context with hypotheses or general knowledge.
```

### Design principles for on-premise models

- Each rule is one sentence, one concrete action
- No abstract instructions ("evaluate trustworthiness") — small models fail on these
- `[PRIMARY]`/`[SUPPORTING]` are explicit text markers — model follows pattern, not reasoning
- Rules overlap with existing prompt lines ("do not invent facts") — deduplicate, keep one version

### Approximate token impact

Current `HYBRID_SYSTEM_PROMPT`: ~400 tokens.
New evidence rules section: ~130 tokens.
Total: ~530 tokens. Increase: ~33% of prompt, <2% of total context budget.

---

## 5. File Changes Summary

| File | Action |
|------|--------|
| `core/interfaces.py` | Add `source_role: str` property to `ConnectorInterface` (default `"knowledge_base"`) |
| `connectors/jira.py` | Set `source_role = "task_tracker"` |
| `connectors/github.py` | Set `source_role = "task_tracker"` |
| `connectors/slack_history.py` | Set `source_role = "communication"` |
| `connectors/files.py` | Set `source_role = "user_upload"` |
| `connectors/confluence.py`, `notion.py`, `gdrive.py` | Keep default `"knowledge_base"` (no change needed) |
| `ingestion/pipeline.py` | Write `source_role` into Qdrant chunk payload |
| `retrieval/search.py` | `_collect_frags()` returns `list[dict]`, new `_mark_evidence_role()`, refactored `_build_ctx()` |
| `retrieval/prompts.py` | Add evidence rules to `HYBRID_SYSTEM_PROMPT` |
| `retrieval/token_budget.py` | Adapt `select_fragments_within_budget()` for `list[dict]` |
| `tests/unit/test_evidence_packs.py` | New: tests for marking, grouping, context assembly, connector roles |

---

## 6. What Stays Unchanged

- Recall channels — retrieval logic untouched, only context formatting changes
- Scoring / reranking — ranking order preserved
- Query classifier — used as-is for profile → primary_role mapping
- Graph enrichment — graph context format unchanged
- `_append_sources()` — source citation appended to answer unchanged
- `TEAM_WORKFLOW_SCHEMA_SYSTEM_PROMPT` — team workflow schema path unchanged

---

## 7. Acceptance Criteria

- [ ] Connectors declare `source_role`; written to Qdrant payload at ingestion
- [ ] `_collect_frags()` returns enriched dicts with source_role, title, date
- [ ] `_mark_evidence_role()` labels PRIMARY/SUPPORTING based on query profile
- [ ] `_build_ctx()` groups fragments by source_role with markdown sections
- [ ] PRIMARY group appears first in context
- [ ] `mixed` profile → all SUPPORTING (zero behavior change)
- [ ] `HYBRID_SYSTEM_PROMPT` contains atomic evidence rules
- [ ] `select_fragments_within_budget()` works with dict format
- [ ] Eval: P@10/MRR/NDCG do not regress (context format change, not recall)
- [ ] Manual spot-check on 10 queries: proper citation, uncertainty marking
- [ ] Tests cover: marking per profile, grouping, empty groups, connector roles, budget with dicts
