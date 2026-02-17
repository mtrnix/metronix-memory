# MTRNIX Core — TODO & Technical Debt

Open-source core (metatron-core). Enterprise features tracked separately in metatron-enterprise.

---

## Completed (2026-02-11)

- [x] Query expansion via LLM — `query_expansion.py`, `expand_query()`
- [x] Language detection (30% Cyrillic threshold) — `detect_response_language()`
- [x] Source diversity (min 2 per source type) — `diversify_results()`
- [x] Smart date extraction (title → content → updated_at → created_at) — `extract_document_date()`
- [x] Relative date support (this week, last week, this month) — `extract_date_range()`
- [x] Date range widening (±7 days fallback when exact range empty)
- [x] Source citations in answers (📄 Confluence, 📋 Jira icons) — `_append_sources()`
- [x] Jira status + assignee in Qdrant metadata — `search_by_status()`, `search_by_assignee()`
- [x] In Progress task injection for activity queries
- [x] Person name aliases (Russian nicknames → Jira display names) — `aliases.py`
- [x] Follow-up detection (independent questions don't get session history) — `_is_follow_up()`
- [x] Query/intent_query parameter fix (language detection uses current message only)
- [x] Handle `/start` command — return greeting response

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
- [ ] Answer length control — system prompt instruction to keep activity answers concise
- [ ] Jira board column names as status source (instead of hardcoded "In Progress", "В работе")
- [ ] Handle "What is X doing?" where X is not a person (currently triggers false positive person detection)

### Smart Metadata Extraction
Replace per-source hardcoded metadata with universal LLM-based extraction at ingestion time.
- [ ] One LLM prompt extracts structured fields from any document: `{dates_mentioned, people, status, priority, topics, document_type}`
- [ ] Fixed output schema, works identically for Confluence, Jira, Notion, files
- [ ] Evaluate cost/speed: ~2-5 sec per doc, can use local model via Ollama
- [ ] Eliminates: hardcoded Jira status/assignee, per-connector metadata mapping

### Date Handling
- [ ] Extract ALL dates mentioned in document, store as list
- [ ] Handle date ranges in titles: "Weekly Report Feb 3-7" → start + end
- [ ] Resolve relative dates in content using document timestamp as reference

### Connectors
- [x] Notion connector (notion-client) — `connectors/notion.py`, `notion_processing.py`
- [ ] GitHub connector (repos, issues, PRs, wiki)
- [ ] Google Drive connector (docs, sheets)
- [ ] Slack history connector (channel messages)
- [ ] File upload connector (PDF/DOCX via API or Telegram)
- [x] Confluence: incremental sync (only modified pages) — `SyncState`, `/sync full`
- [x] Jira: incremental sync (only updated issues) — `SyncState`, `/sync full`
- [ ] Jira: custom fields support
- [ ] Jira: sprint information indexing

### Agent & Bot
- [ ] `/connect` wizard — add credentials via Telegram chat
- [ ] Multi-step tool calls (LLM → search → refine → answer)
- [ ] File upload in Telegram (user sends PDF → indexed)
- [ ] Group chat support (respond to @mentions)

### Channels
- [ ] Slack channel (slack-bolt, Socket Mode)
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
- [ ] Temporal facts — entity version history
- [ ] Graph-based query routing — detect when traversal helps vs pure vector
- [ ] Entity deduplication ("Женя" = "Евгений Щербинин" = "Evgeny Shcherbinin")
- [ ] Graph visualization API

### Observability
- [ ] Benchmarker API — `/api/v1/query/trace` with full 7-step trace
- [ ] Auto-sync scheduler (cron-based periodic re-sync)
- [ ] Sync logs table with error capture
- [ ] Health dashboard (status, counts, latency)

### Infrastructure
- [ ] Connection credentials in PostgreSQL (encrypted), not just .env
- [ ] Docker Compose production hardening (limits, healthchecks, restart)
- [ ] Centralized structured logging

### Auth
- [ ] Telegram user → internal role mapping
- [ ] Audit trail (who searched what, when)

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
**Next step:** Combine with LLM metadata extraction at ingestion for best of both.

### 2026-02-11: Smart Date from Title over Timestamp
**Decision:** Extract dates from document titles first, fall back to updated_at.
**Rationale:** "2026-01-27 Summary" edited on Feb 2 should match Jan 27 searches. Content date > edit timestamp.

### 2026-02-11: Source Diversity over Source Priority
**Decision:** Min 2 results per source type instead of strict Confluence > Jira priority.
**Rationale:** Jira is more relevant for activity questions, Confluence for architecture. Let the LLM decide.

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
