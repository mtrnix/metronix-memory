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

1. **`ConnectorInterface`** — new non-abstract class attribute `source_role: str = "knowledge_base"` (safest fallback — most connectors are documentation sources). This is a concrete attribute, not an abstract property, since it has a sensible default. Note: `ConnectorInterface` is in `core/interfaces.py` — changes require coordination with enterprise repo per project rules.

2. **Each connector class** — overrides the default:
   - `JiraConnector.source_role = "task_tracker"`
   - `GithubConnector.source_role = "task_tracker"`
   - `SlackHistoryConnector.source_role = "communication"`
   - `FilesConnector.source_role = "user_upload"`
   - `ConfluenceConnector`, `NotionConnector`, `GDriveConnector` — keep default `"knowledge_base"`

3. **Connection record (DB)** — **Descoped for this task.** Per-connection `source_role_override` would require an Alembic migration and API changes. The class-level default covers all current use cases. Override can be added later when an admin UI exists. YAGNI.

### How source_role reaches fragments

Data flow: connector class → `Document` model → ingestion pipeline → Qdrant payload → recall result.

1. **`Document` model** (`core/models.py`) — new optional field `source_role: str = ""`.
2. **`ingest_documents()`** (`pipeline.py`) — already accepts `connector_type: str` param. Add `source_role: str = "knowledge_base"` param. Written into Qdrant chunk payload (line 210, alongside `"type": doc.source_type`). Callers (sync triggers in `api/routes/connections.py` and `api/routes/chat.py` upload) pass `source_role` from the connector instance or connection config.
3. **`_format_result()`** (`storage/qdrant.py`) — extract `source_role` from payload into result dict: `"source_role": payload.get("source_role", "knowledge_base")`. The default `"knowledge_base"` provides graceful fallback for chunks indexed before reindex.
4. **Recall results** — each result dict now includes `source_role` key, consumed by `_collect_frags()`.

**Reindex required** after deployment — existing chunks lack `source_role` in payload. Full reindex is acceptable (dataset is small). During the window between deployment and reindex, `_format_result()` defaults to `"knowledge_base"`.

---

## 2. Evidence Marking

### Descoped: Contradictory evidence category

The original task mentions 4 categories including "contradictory evidence". This is descoped as a structural category. Reason: detecting contradiction requires semantic analysis (NLI), not metadata. Instead, the system prompt instructs the LLM to identify and flag contradictions at answer generation time (see Section 4). This is sufficient because the LLM already reads all fragments and can reason about semantic conflicts — no pre-classification needed.

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

New function `_mark_evidence_role(frags, query_profile)` in `search.py`, called after `_collect_frags()` and before `_build_ctx()`:

```python
# In hybrid_search_and_answer(), after line 521:
frags, seen_h, total_c, doc_stats = _collect_frags(base, set(), 0)
_mark_evidence_role(frags, classification["profile"])
```

For each fragment dict:
- If `frag["source_role"] == primary_role` for current profile → `frag["evidence_marker"] = "PRIMARY"`
- Else → `frag["evidence_marker"] = "SUPPORTING"`
- If `primary_role is None` → all `"SUPPORTING"`

Unknown `source_role` values → `"SUPPORTING"` (safe fallback).

### Fragment text format in context

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
- The source_role group that contains PRIMARY-marked fragments appears first (only one `primary_role` per profile, so exactly one group has PRIMARY fragments)
- Remaining groups in fixed order: `knowledge_base`, `task_tracker`, `user_upload`, `communication`
- Empty groups are skipped (no empty sections in output)
- If all fragments are from one source_role (e.g., all Confluence) — single section, all PRIMARY for matching profile. This is acceptable.
- Graph context remains as-is (already a separate section)

### `_collect_frags()` return type change

Current: `list[str]`
New: `list[dict]` where each dict:

```python
{
    "text": str,              # fragment text (without markers — added by _build_ctx)
    "source_type": str,       # "jira", "confluence", etc.
    "source_role": str,       # "task_tracker", "knowledge_base", etc.
    "title": str,             # document title
    "date": str | None,       # document date if available
    "doc_label": str,         # for FinOps tracking
    "evidence_marker": str,   # "PRIMARY" or "SUPPORTING" (set by _mark_evidence_role)
}
```

### Downstream consumers updated

- **`select_fragments_within_budget(frags, ...)`** — new signature accepts `list[dict]`, operates on `frag["text"]` for token estimation, returns `list[dict]` (preserving metadata). Callers updated.
- **Trace logging** (`return_trace` path, line 594-598) — `"fragments"` field in trace result becomes `list[dict]`. `_token_budget_used` computed as `sum(len(f["text"]) for f in frags)`. `source_word_count` computed as `sum(len(f["text"].split()) for f in frags)`. Benchmarker API consumers must handle dict format.
- **`_append_sources()`** — unchanged, operates on `base` (result dicts), not `frags`.

### Token budget

Overhead from grouped format: section headers (~4-5 per context × ~5 tokens each = ~25 tokens) + `[PRIMARY]`/`[SUPPORTING]` markers (~3 tokens × ~25 fragments = ~75 tokens) + dates (~3 tokens × ~25 fragments = ~75 tokens) ≈ **~175 extra tokens**. With a budget of 6000-8000 tokens, this is ~2-3%. Acceptable.

---

## 4. System Prompt Update

### New evidence rules section

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

### Lines removed from existing prompt (deduplication)

These existing lines in `HYBRID_SYSTEM_PROMPT` overlap with evidence rules and are removed:

- `"Do not invent facts that are not in the provided fragments."` → replaced by "Never mix facts from context with hypotheses or general knowledge." + "If the context is insufficient to answer, say so directly."
- `"Use text fragments as the primary source of facts."` → replaced by evidence rules about PRIMARY/SUPPORTING.

All other existing lines (language rules, source references with `[$[title]$]`, response length guidelines) remain unchanged.

### Design principles for on-premise models

- Each rule is one sentence, one concrete action
- No abstract instructions ("evaluate trustworthiness") — small models fail on these
- `[PRIMARY]`/`[SUPPORTING]` are explicit text markers — model follows pattern, not reasoning

### Approximate token impact

Current `HYBRID_SYSTEM_PROMPT`: ~400 tokens.
Removed lines: ~-30 tokens.
New evidence rules section: ~130 tokens.
Net change: ~+100 tokens → ~500 tokens total. <2% of total context budget.

---

## 5. File Changes Summary

| File | Action |
|------|--------|
| `core/interfaces.py` | Add `source_role: str = "knowledge_base"` class attribute to `ConnectorInterface`. **Requires enterprise repo coordination.** |
| `core/models.py` | Add `source_role: str = ""` field to `Document` dataclass |
| `connectors/jira.py` | Set `source_role = "task_tracker"` |
| `connectors/github.py` | Set `source_role = "task_tracker"` |
| `connectors/slack_history.py` | Set `source_role = "communication"` |
| `connectors/files.py` | Set `source_role = "user_upload"` |
| `connectors/confluence.py`, `notion.py`, `gdrive.py` | Keep default `"knowledge_base"` (no change needed) |
| `ingestion/pipeline.py` | Add `source_role` param to `ingest_documents()`, write into Qdrant chunk payload |
| `api/routes/connections.py` | Pass `connector.source_role` to `ingest_documents()` during sync |
| `storage/qdrant.py` | Add `"source_role": payload.get("source_role", "knowledge_base")` to `_format_result()` |
| `retrieval/search.py` | `_collect_frags()` returns `list[dict]`, new `_mark_evidence_role()`, refactored `_build_ctx()`, updated trace logging |
| `retrieval/prompts.py` | Add evidence rules to `HYBRID_SYSTEM_PROMPT`, remove deduplicated lines |
| `retrieval/token_budget.py` | Adapt `select_fragments_within_budget()`: accepts `list[dict]`, returns `list[dict]`, operates on `frag["text"]` |
| `tests/unit/test_evidence_packs.py` | New: tests for marking, grouping, context assembly, connector roles, budget with dicts |

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
- [ ] `Document` model has `source_role` field; populated during sync
- [ ] `_format_result()` extracts `source_role` from payload with fallback
- [ ] `_collect_frags()` returns enriched dicts with source_role, title, date
- [ ] `_mark_evidence_role()` labels PRIMARY/SUPPORTING based on query profile
- [ ] `_build_ctx()` groups fragments by source_role with markdown sections
- [ ] Source_role group containing PRIMARY fragments appears first in context
- [ ] `mixed` profile → all SUPPORTING (zero behavior change)
- [ ] `HYBRID_SYSTEM_PROMPT` contains atomic evidence rules; deduplicated lines removed
- [ ] `select_fragments_within_budget()` works with `list[dict]` format
- [ ] Trace logging (`return_trace`) adapted for dict fragments
- [ ] Eval: P@10/MRR/NDCG do not regress (context format change, not recall)
- [ ] Manual spot-check on 10 queries: proper citation, uncertainty marking
- [ ] Tests cover: marking per profile, grouping, empty groups, single source_role, connector roles, budget with dicts, trace format
