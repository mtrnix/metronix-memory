# MTRNIX Core — TODO & Technical Debt

Open-source core (metatron-core). Enterprise features tracked separately in metatron-enterprise.

---

## Completed

### 2026-02-11 — Search Quality
- [x] Query expansion via LLM — `query_expansion.py`, `expand_query()`
- [x] Language detection (30% Cyrillic threshold) — `detect_response_language()`
- [x] Source diversity (min 2 per source type) — `diversify_results()`
- [x] Smart date extraction (title → content → updated_at → created_at) — `extract_document_date()`
- [x] Relative date support (this week, last week, this month) — `extract_date_range()`
- [x] Date range widening (±7 days fallback when exact range empty)
- [x] Source citations in answers (Confluence, Jira, Notion icons) — `_append_sources()`
- [x] Jira status + assignee in Qdrant metadata — `search_by_status()`, `search_by_assignee()`
- [x] In Progress task injection for activity queries
- [x] Person name aliases (Russian nicknames → Jira display names) — `aliases.py`
- [x] Follow-up detection (independent questions don't get session history) — `_is_follow_up()`
- [x] Query/intent_query parameter fix (language detection uses current message only)
- [x] Handle `/start` command — return greeting response

### 2026-02-12 — Connectors & Sync
- [x] Notion connector (notion-client) — `connectors/notion.py`, `notion_processing.py`
- [x] Confluence: incremental sync (only modified pages) — `SyncState`, `/sync full`
- [x] Jira: incremental sync (only updated issues) — `SyncState`, `/sync full`

### 2026-02-13 — Knowledge Graph
- [x] Parallel graph extraction — 4x sync speedup — `ingestion/pipeline.py`
- [x] Token-aware context loading for LLM — graph context budget cap
- [x] Graph entity quality — role filter, name merge, sentence filter
- [x] Temporal facts — entity version history with date tracking

### 2026-02-14 — MCP Client
- [x] MCP Client — SSE transport, tool listing, tool execution — `mcp/client.py`
- [x] GenericMCPAdapter — two-phase strategy (read tools → sync, action tools → execute) — `mcp/adapter.py`
- [x] MCP server registry — persistent JSON config per workspace — `mcp/registry.py`, `mcp/config.py`
- [x] MCP sync integration — `/mcp sync`, `/mcp sync-all` — `mcp/sync.py`
- [x] Action planner + executor — LLM picks tool + args, executes via MCP — `mcp/action_planner.py`, `mcp/action_executor.py`
- [x] ACTION intent classification — "create", "update", "send" keywords → MCP execution

### 2026-02-15 — REST API & Infrastructure
- [x] REST API polish — CORS, SSE streaming, error sanitization, async health probes
- [x] File upload API — PDF/DOCX/TXT/MD via multipart upload — `api/routes/files.py`
- [x] Memgraph retry decorator — auto-reconnect on stale connections — `storage/memgraph.py`
- [x] Jira key exact match — PROJ-123 patterns get direct doc_label lookup — `retrieval/search.py`
- [x] Russian case ending normalization — "Вадима"/"Вадимом" → "Вадим" — `retrieval/alias_registry.py`
- [x] Slack bot — Socket Mode — `channels/slack_bot.py`
- [x] Discord bot — `channels/discord_bot.py`

---

## P0 — Current Iteration

### Bot UX
- [ ] Reduce answer verbosity — too much architectural context in activity answers
- [ ] Fix Markdown formatting fallback — some LLM responses break Telegram's parser

### Search Quality
- [ ] Tune system prompt for shorter, focused answers on activity questions
- [ ] Verify "this week" queries when no data exists for exact date range

---

## P1 — Next Iteration

### Search Quality
- [ ] Person name resolution via LLM (replace static NAME_ALIASES dict)
- [ ] Jira board column names as status source (instead of hardcoded "In Progress", "В работе")
- [ ] Handle "What is X doing?" where X is not a person (false positive person detection)

### Smart Metadata Extraction
Replace per-source hardcoded metadata with universal LLM-based extraction at ingestion time.
- [ ] One LLM prompt extracts structured fields: `{dates_mentioned, people, status, priority, topics, document_type}`
- [ ] Fixed output schema, works identically for Confluence, Jira, Notion, files
- [ ] Evaluate cost/speed: ~2-5 sec per doc, can use local model via Ollama

### Date Handling
- [ ] Extract ALL dates mentioned in document, store as list
- [ ] Handle date ranges in titles: "Weekly Report Feb 3-7" → start + end
- [ ] Resolve relative dates in content using document timestamp as reference

### Connectors
- [ ] GitHub connector (repos, issues, PRs, wiki)
- [ ] Google Drive connector (docs, sheets)
- [ ] Slack history connector (channel messages)
- [ ] Jira: custom fields support
- [ ] Jira: sprint information indexing

### Agent & Bot
- [ ] `/connect` wizard — add credentials via Telegram chat
- [ ] Multi-step tool calls (LLM → search → refine → answer)
- [ ] File upload in Telegram (user sends PDF → indexed)
- [ ] Group chat support (respond to @mentions)

### Channels
- [ ] Web UI chat interface

---

## P2 — Future Improvements

### Search & Retrieval
- [ ] Query expansion prompt tuning from usage logs
- [ ] NER entity extraction at indexing (spaCy/natasha for Russian) as fast LLM alternative
- [ ] Re-ranking stage (cross-encoder or LLM-based)
- [ ] Missing context detection — flag when answer confidence is low
- [ ] Source freshness weighting — recently updated docs scored higher
- [ ] User feedback loop — thumbs up/down feeds scoring weights

### Knowledge Graph
- [ ] Graph-based query routing — detect when traversal helps vs pure vector
- [ ] Entity deduplication ("Женя" = "Евгений Щербинин" = "Evgeny Shcherbinin")
- [ ] Graph visualization API

### Observability
- [ ] Auto-sync scheduler (cron-based periodic re-sync)
- [x] Sync logs table with error capture
- [x] Health dashboard (status, counts, latency) — 5/9 endpoints implemented (overview, sync-history, ingestion-errors, query-trend, graph-stats)

### Infrastructure
- [ ] Connection credentials in PostgreSQL (encrypted), not just .env
- [ ] Docker Compose production hardening (limits, healthchecks, restart)
- [ ] Centralized structured logging
- [ ] **Workspace storage consolidation** — currently workspaces are duplicated in Memgraph (source of truth) and PostgreSQL (for foreign keys). Consider: (1) moving to PostgreSQL-only with optional Memgraph sync for graph queries, or (2) removing foreign key constraints and using workspace_id as plain string

### Auth
- [ ] Telegram user → internal role mapping
- [ ] Audit trail (who searched what, when)

### Audio Transcription Integration
Replace standalone Discord transcription bot with native audio processing in Metatron.
- [ ] Audio processor — accept .mp3, .wav, .ogg, .m4a, .webm files
- [ ] Transcription via Whisper model through Ollama (already in stack)
- [ ] Entry points: Telegram voice messages, Discord audio, REST API upload, MCP
- [ ] Transcribed text flows through existing ingestion pipeline (chunk → embed → store)

---

## Architecture Decisions Log

### 2026-02-11: Person-specific vs General Activity Injection (elif pattern)
**Decision:** When a specific person is detected in the query, inject ONLY their tasks. Do NOT also inject all In Progress tasks.
**Rationale:** Mixing 15 general In Progress tasks with 10 person-specific tasks diluted the person's results after diversify_results(). The elif pattern ensures person queries are focused.

### 2026-02-11: Follow-up Detection for Session History
**Decision:** Only prepend conversation history for follow-up queries (pronouns, short messages, continuation words). Independent questions get no history.
**Rationale:** "What is Metatron?" after "Что делает Женя?" was getting contaminated with team activity context from session history. Demonstratives (this/that) excluded from follow-up indicators to avoid false positives with "this week".

### 2026-02-11: Query Expansion over Hardcoded Filters
**Decision:** LLM-based query expansion instead of per-source metadata filters.
**Rationale:** Hardcoded filters don't scale — every new source needs custom code. Query expansion works universally: LLM adds keywords (e.g. "In Progress") that BM25 matches in text.
**Tradeoff:** +1-2 sec per query. Acceptable for MVP.

### 2026-02-11: Smart Date from Title over Timestamp
**Decision:** Extract dates from document titles first, fall back to updated_at.
**Rationale:** "2026-01-27 Summary" edited on Feb 2 should match Jan 27 searches. Content date > edit timestamp.

### 2026-02-11: Source Diversity over Source Priority
**Decision:** Min 2 results per source type instead of strict Confluence > Jira priority.
**Rationale:** Jira is more relevant for activity questions, Confluence for architecture. Let the LLM decide.

### 2026-02-14: MCP Two-Phase Adapter Strategy
**Decision:** GenericMCPAdapter classifies each tool as "read" (for sync) or "action" (for execution) based on naming conventions and schema heuristics.
**Rationale:** MCP servers expose both read-only tools (list_pages, search_issues) and write tools (create_issue, send_message). Sync should only call read tools. Action execution should only call write tools.

### 2026-02-15: Memgraph Retry over Connection Pooling
**Decision:** Retry decorator with driver reset on ServiceUnavailable/SessionExpired, rather than connection pool tuning.
**Rationale:** Long LLM extraction calls (10-16s) cause Memgraph connections to go stale. Pool settings don't help because the idle timeout is server-side. Resetting the driver singleton and retrying is simpler and more reliable.

---

## Metrics to Track

- Search latency: p50, p95, p99
- LLM call latency per provider
- Query expansion latency
- Answer quality: user feedback
- Source distribution in answers
- Date filter hit rate
- Sync success rate
- Documents indexed per source
