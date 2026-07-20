# Conversation Compaction Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist temporary conversational events, compact them into private source-linked ledgers and candidate memories, and inject the ledger into proxy context.

**Tracking:** GitHub #343. The automatic-write policy work is GitHub #344; session promotion and retrieval-feedback follow-ups are #345 and #346.

**Architecture:** PostgreSQL is authoritative for events and ledgers. A deterministic, flag-gated controller compacts a session at explicit, inactivity, event-count, or token-budget triggers; it writes a ledger and policy-approved candidate records through `MemoryService`. Raw event text is deleted by the retention worker after the configured TTL, leaving provenance on durable artifacts.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, Pydantic, pytest.

## Global Constraints

- Keep automatic compaction disabled by default.
- Default raw event retention is 7 days; supported values are 24h, 7d, 30d, and forever.
- Durable writes default to `MemoryScope.PER_AGENT`; promotion is explicit.
- Never retain secrets, credential-like values, or untrusted embedded instructions automatically.
- All behavior must work without an external LLM in tests.

---

### Task 1: Persist temporary events and durable ledgers

**Files:**
- Create: `migrations/versions/029_conversation_compaction.py`
- Create: `src/metronix/memory/conversation_models.py`
- Create: `src/metronix/storage/conversation_postgres.py`
- Test: `tests/integration/memory/test_conversation_postgres.py`

**Interfaces:**
- Produces `ConversationEvent`, `SessionLedger`, `ConversationPostgresStore.append_event()`, `list_uncompacted()`, `save_ledger()`, and `expire_events()`.
- Consumes `workspace_id`, `agent_id`, and `session_id` from proxy/MCP callers.

- [ ] **Step 1: Write the failing persistence tests**

```python
async def test_expiring_events_retains_ledger_provenance(store):
    event = ConversationEvent.new("ws", "agent-a", "s-1", "user", "hello")
    await store.append_event(event)
    await store.save_ledger(SessionLedger.new(event, source_hashes=[event.content_hash]))
    assert await store.expire_events(older_than=datetime.now(UTC) + timedelta(seconds=1)) == 1
    assert (await store.get_ledger("ws", "agent-a", "s-1")).source_hashes == [event.content_hash]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest tests/integration/memory/test_conversation_postgres.py -q`

Expected: FAIL because `ConversationPostgresStore` does not exist.

- [ ] **Step 3: Add the migration, dataclasses, and store**

```python
@dataclass
class ConversationEvent:
    id: str; workspace_id: str; agent_id: str; session_id: str
    role: str; content: str; content_hash: str; created_at: datetime

@dataclass
class SessionLedger:
    id: str; workspace_id: str; agent_id: str; session_id: str
    summary: dict[str, object]; source_hashes: list[str]; created_at: datetime
```

Create `conversation_events` with a TTL index on `(workspace_id, expires_at)` and `session_ledgers` with a unique `(workspace_id, agent_id, session_id, generation)` index. Implement parameterized SQL only; delete event content rows, never ledger provenance, in `expire_events`.

- [ ] **Step 4: Run persistence tests**

Run: `uv run --extra dev pytest tests/integration/memory/test_conversation_postgres.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add migrations/versions/029_conversation_compaction.py src/metronix/memory/conversation_models.py src/metronix/storage/conversation_postgres.py tests/integration/memory/test_conversation_postgres.py
git commit -m "feat: persist temporary conversation events"
```

### Task 2: Add policy-gated deterministic compaction

**Files:**
- Create: `src/metronix/memory/compaction.py`
- Create: `src/metronix/memory/compaction_policy.py`
- Modify: `src/metronix/core/config.py`
- Modify: `src/metronix/memory/service.py`
- Test: `tests/unit/memory/test_compaction.py`
- Test: `tests/unit/memory/test_compaction_policy.py`

**Interfaces:**
- Consumes `ConversationPostgresStore` and `MemoryService`.
- Produces `CompactionController.compact(workspace_id, agent_id, session_id, reason)` and `MemoryCandidate`.

- [ ] **Step 1: Write failing policy and controller tests**

```python
def test_policy_rejects_secret_and_accepts_explicit_preference():
    assert evaluate_candidate("api_key=secret", explicit=False).decision is Decision.REJECT
    assert evaluate_candidate("User prefers tea", explicit=True).status is LifecycleStatus.ACTIVE

async def test_compact_writes_candidate_and_private_ledger(controller):
    result = await controller.compact("ws", "agent-a", "s-1", reason="session_end")
    assert result.ledger.agent_id == "agent-a"
    assert result.memory_records[0].scope is MemoryScope.PER_AGENT
    assert result.memory_records[0].status is LifecycleStatus.CANDIDATE
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run --extra dev pytest tests/unit/memory/test_compaction.py tests/unit/memory/test_compaction_policy.py -q`

Expected: FAIL because compaction modules do not exist.

- [ ] **Step 3: Implement the controller and policy**

```python
class CompactionController:
    async def compact(self, workspace_id: str, agent_id: str, session_id: str, *, reason: str) -> CompactionResult:
        events = await self._events.list_uncompacted(workspace_id, agent_id, session_id)
        ledger, candidates = self._extractor.extract(events)
        await self._events.save_ledger(ledger)
        return await self._persist_candidates(workspace_id, candidates)
```

Use a deterministic fixture extractor in core that creates only structured candidate inputs; inject any model-backed extractor later. Add settings for `conversation_compaction_enabled`, `conversation_event_retention`, `conversation_compaction_max_events`, and `conversation_compaction_idle_minutes`. Ensure rejected content is not logged.

- [ ] **Step 4: Run unit tests**

Run: `uv run --extra dev pytest tests/unit/memory/test_compaction.py tests/unit/memory/test_compaction_policy.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/memory/compaction.py src/metronix/memory/compaction_policy.py src/metronix/core/config.py src/metronix/memory/service.py tests/unit/memory/test_compaction.py tests/unit/memory/test_compaction_policy.py
git commit -m "feat: add policy-gated conversation compaction"
```

### Task 3: Wire proxy capture, API controls, expiry, and context injection

**Files:**
- Modify: `src/metronix/proxy/service.py`
- Modify: `src/metronix/memory/assembler.py`
- Create: `src/metronix/api/routes/conversations.py`
- Modify: `src/metronix/api/app.py`
- Create: `src/metronix/memory/conversation_worker.py`
- Test: `tests/integration/api/test_conversation_compaction.py`

**Interfaces:**
- Consumes `CompactionController.compact()` and `SessionLedger`.
- Produces `POST /api/v1/conversations/{session_id}/compact` and a `<session_ledger>` prompt section.

- [ ] **Step 1: Write the end-to-end failing test**

```python
async def test_compacted_ledger_is_injected_without_raw_event_text(client):
    await seed_event(client, content="temporary verbose text")
    await client.post("/api/v1/conversations/s-1/compact")
    prompt = await assemble_context(client, "agent-a", "What do I prefer?")
    assert "<session_ledger>" in prompt
    assert "temporary verbose text" not in prompt
```

- [ ] **Step 2: Run it to verify failure**

Run: `uv run --extra dev pytest tests/integration/api/test_conversation_compaction.py -q`

Expected: FAIL with 404 or missing ledger section.

- [ ] **Step 3: Implement wiring**

```python
await self._events.append_proxy_messages(workspace_id, agent_id, session_id, messages)
if self._settings.conversation_compaction_enabled:
    await self._compaction.maybe_compact(workspace_id, agent_id, session_id)
```

Add the route under authenticated workspace scope, invoke compaction explicitly, and add `_build_session_ledger_section()` to `AgentContextAssembler`. Run the expiry worker only when compaction is enabled; emit activity events with ids/counts but no event content.

- [ ] **Step 4: Run integration tests**

Run: `uv run --extra dev pytest tests/integration/api/test_conversation_compaction.py tests/unit/test_memory_context_mcp.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/metronix/proxy/service.py src/metronix/memory/assembler.py src/metronix/api/routes/conversations.py src/metronix/api/app.py src/metronix/memory/conversation_worker.py tests/integration/api/test_conversation_compaction.py
git commit -m "feat: compact proxy conversation sessions"
```
