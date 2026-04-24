# Pre-rollout follow-ups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** close the four MTRNIX-319 follow-ups: (1) fix the eval event-loop flake by collapsing the 29-query loop to a single `asyncio.run` with a freshly-cleared client cache; (2) refresh the eval dataset to v1.4 by rewriting four temporal/status queries to topic-anchored form and marking two sprint-anchored queries `stable: false`; (3) harden the Agent Registry lifecycle by rejecting `start|stop|pause` from `ARCHIVED` with HTTP 400 and adding a new `POST /api/v1/agents/{id}/restore` (`ARCHIVED → STOPPED`); (4) add ONE integration smoke test covering `/v1/chat/completions` (200 + citations + non-ASCII).

**Architecture:**
- Item 1 — `scripts/run_eval.py` only. Production code untouched.
- Item 2 — `src/metatron/benchmarker/fixtures/search_quality_testset.yaml` only. The v1.4 bump and `stable: false` flags are honoured by the existing aggregate filter at `scripts/run_eval.py:87`.
- Item 3 — `src/metatron/agents/service.py` (new error class + matrix check + `restore_agent`), `src/metatron/agents/__init__.py` (re-export), `src/metatron/api/routes/agents.py` (new route + 400 mapping). No persistence change. No migration.
- Item 4 — `tests/integration/api/test_openai_compat_smoke.py` + `tests/integration/api/__init__.py`. No source change.

**Tech Stack:** Python 3.12, asyncio, FastAPI, pydantic v2, pytest (`asyncio_mode = "auto"`), structlog, PyYAML.

**Jira:** MTRNIX-323
**Depends on:** MTRNIX-316 (merged), MTRNIX-319 (merged), MTRNIX-322 (merged).
**Spec:** `docs/superpowers/specs/2026-04-25-pre-rollout-followups-design.md`
**Branch:** `feature/MTRNIX-323` (already checked out).

---

## Layer Boundary Summary

| File | Layer | Allowed imports |
|---|---|---|
| `scripts/run_eval.py` (modify) | tooling | `metatron.retrieval.search`, `metatron.storage.qdrant.clear_store_cache`, existing |
| `src/metatron/benchmarker/fixtures/search_quality_testset.yaml` (modify) | fixture | n/a |
| `src/metatron/agents/service.py` (modify) | L3 | existing only — `core.exceptions`, `agents.models`, `agents.persistence` |
| `src/metatron/agents/__init__.py` (modify) | L3 | re-export |
| `src/metatron/api/routes/agents.py` (modify) | L6 | existing only |
| `src/metatron/agents/.claude/CLAUDE.md` (modify) | doc | n/a |
| `docs/ROLLOUT_NOTES_2026-04-24.md` (modify) | doc | n/a |
| `CHANGELOG.md` (modify) | doc | n/a |
| `tests/integration/api/__init__.py` (new) | test | n/a |
| `tests/integration/api/test_openai_compat_smoke.py` (new) | test | `metatron.api.app`, `metatron.core.config`, `fastapi.testclient`, `pytest` |
| `tests/unit/test_agents_service.py` (modify) | test | existing |
| `tests/unit/test_agents_routes.py` (modify) | test | existing |

**Not touched:** `core/interfaces.py`, `core/events.py`, `core/models.py`, `storage/*`, `retrieval/*`, `mcp/*`, `memory/*`, `freshness/*`, `connectors/*`, all migrations.

**No upward imports.** `agents.service` (L3) ← `api.routes.agents` (L6); same edges as today.

---

## Config Vars

**None added.** All four items reuse existing settings.

---

## Event Constants

**None added.** `core/events.py` unchanged.

---

## Backward Compatibility Guarantee

- Item 1: `hybrid_search_and_answer_sync` retained in `retrieval/search.py` for the AgentRouter and confidence eval that still call it via `asyncio.run`. The eval driver simply stops being a caller.
- Item 2: `version: "1.4"` is a doc-level bump; `EvalQuery` schema is unchanged. Existing snapshots in `eval_results/` keep loading.
- Item 3: **Breaking-ish for REST.** `POST /api/v1/agents/{id}/start|stop|pause` on ARCHIVED moves from 200 (un-archive side effect) to 400. CHANGELOG `### Changed`. Per MTRNIX-319 §5, no live consumer.
- Item 3: existing `delete_agent`, `start_agent`, `stop_agent`, `pause_agent` for non-archived sources — unchanged behaviour.
- Item 3: existing soft-delete + `GET` after DELETE returning 200 (archived) — unchanged.
- Item 3: existing partial-unique-index on `(workspace_id, name) WHERE status <> 'archived'` (MTRNIX-270) — unchanged. Restore returns to STOPPED, so the name slot is re-claimed; if a fresh agent was created with the same name in the meantime, restore will fail at the partial-unique constraint. **Detect and remap to `AgentNameConflictError` (409)** in `restore_agent`.
- Item 4: test-only addition; no runtime change.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| modify | `scripts/run_eval.py` | Convert `run_eval` to async; call `clear_store_cache()` then `asyncio.run` from `main`. |
| modify | `src/metatron/benchmarker/fixtures/search_quality_testset.yaml` | v1.3 → v1.4 with rewrites + `stable: false` flags. |
| modify | `src/metatron/agents/service.py` | Add `AgentInvalidStateTransitionError`; validate source state in `_transition_status`; new `restore_agent`. |
| modify | `src/metatron/agents/__init__.py` | Re-export `AgentInvalidStateTransitionError`. |
| modify | `src/metatron/api/routes/agents.py` | Add 400 mapping; add `POST /{id}/restore`. |
| modify | `src/metatron/agents/.claude/CLAUDE.md` | Replace un-delete caveat with state matrix + `/restore` line. |
| modify | `docs/ROLLOUT_NOTES_2026-04-24.md` | Trim 4 stanzas → "Resolved in MTRNIX-323". |
| modify | `CHANGELOG.md` | 4 entries under `[Unreleased]`. |
| new | `tests/integration/api/__init__.py` | Empty package marker. |
| new | `tests/integration/api/test_openai_compat_smoke.py` | Single smoke test. |
| modify | `tests/unit/test_agents_service.py` | New `TestStateTransitionMatrix` (16 cells) + `TestRestore`. |
| modify | `tests/unit/test_agents_routes.py` | New `/restore` route tests + `/start`-from-ARCHIVED 400 test. |

---

## Implementation Order

The four items are independent. Recommended order: **2 → 1 → 3 → 4** (data first, then driver, then API change, then test).

---

## Phase 1 — Item 2: Dataset v1.4

- [ ] Open `src/metatron/benchmarker/fixtures/search_quality_testset.yaml`.
- [ ] Bump `version: "1.3"` → `version: "1.4"`.
- [ ] Update `description` last line: append `Last updated 2026-04-25 (v1.4: temporal/status queries de-pinned to semantic markers and sprint-anchored queries marked unstable — MTRNIX-323).`.
- [ ] Edit `exec-02`:
  - `text:` → `"What tickets describe Hermes integration and standup workflows?"`
  - `expected_doc_labels:` → `["MTRNIX-255", "MTRNIX-224"]` (drop `MTRNIX-164`).
  - `notes:` → `"Topic-anchored Hermes/standup tickets — MTRNIX-323"`.
- [ ] Edit `time-01`:
  - `text:` → `"What tickets cover Hermes-native standup setup and demo prep?"`
  - `expected_doc_labels:` → `["MTRNIX-255", "MTRNIX-253", "MTRNIX-254"]`.
  - `notes:` → `"Topic-anchored standup + demo tickets — MTRNIX-323"`.
- [ ] Edit `time-03`:
  - `text:` → `"What documents and tickets describe the MCP client integration?"`
  - `expected_doc_labels:` → `["MTRNIX-125", "MTRNIX-35"]`.
  - `notes:` → `"Topic-anchored MCP integration — MTRNIX-323"`.
- [ ] Edit `time-05`: add `stable: false`. Update `notes:` → `"Sprint-identity query, requires sprint metadata in retrievable payload — re-enable after sprint-aware retrieval lands. (MTRNIX-323)"`.
- [ ] Edit `agg-01`: add `stable: false`. Update `notes:` (same wording).
- [ ] Edit `ru-02`:
  - `text:` → `"Какие тикеты описывают интеграцию Hermes и standup-процессы?"`
  - `expected_doc_labels:` → `["MTRNIX-255", "MTRNIX-224"]`.
  - `notes:` → `"Russian mirror of exec-02; topic-anchored — MTRNIX-323"`.
- [ ] **Verification gate:** load YAML via `python -c "from metatron.benchmarker.services.eval_loader import load_eval_testset_from_path, DEFAULT_TESTSET_PATH; ts = load_eval_testset_from_path(DEFAULT_TESTSET_PATH); print(ts.version, len(ts.queries))"` — confirms parse succeeds and version reads as `"1.4"`.

## Phase 2 — Item 1: eval driver

- [ ] Open `scripts/run_eval.py`.
- [ ] Add import `from metatron.storage.qdrant import clear_store_cache` and `from metatron.retrieval.search import hybrid_search_and_answer` (replacing the existing `hybrid_search_and_answer_sync` import).
- [ ] Convert `def run_eval(...)` to `async def run_eval(...)`.
- [ ] Inside `run_eval`, replace the two `hybrid_search_and_answer_sync(q.text, workspace, k, None, None, return_trace=True)` calls with `await hybrid_search_and_answer(query=q.text, user_id=workspace, k=k, workspace_id=None, intent_query=None, return_trace=True)`.
  - Note the kwarg names — `hybrid_search_and_answer` uses `query=` not the positional first arg.
  - Confirm by reading `retrieval/search.py:802` signature.
- [ ] In `main()`, immediately before the call to `run_eval`, call `clear_store_cache()`.
- [ ] Wrap the call: `results = asyncio.run(run_eval(args.workspace, args.k, testset_path, include_unstable=args.all))`.
- [ ] Add `import asyncio` if not already at module top.
- [ ] **Verification gate:** run `make eval` once locally (or against a populated workspace). Inspect logs:
  - [ ] `grep -c "qdrant.async.hybrid_search.fallback" <eval log>` returns `0`.
  - [ ] All 27 `stable: true` queries (29 - 2 newly-unstable) report metric values.
  - [ ] No `RuntimeError: Event loop is closed` traceback.
- [ ] Run `make eval-save` to refresh the baseline under `eval_results/`. Commit the baseline file alongside the code change so future `make eval-compare` is honest.

## Phase 3 — Item 3: Agent Registry hardening

### 3a — Service-layer changes

- [ ] Open `src/metatron/agents/service.py`.
- [ ] Add new error class after `AgentNameConflictError`:
  ```python
  class AgentInvalidStateTransitionError(MetatronError):
      """Requested lifecycle transition is not allowed from the current status."""
  ```
- [ ] Add module-private constant after the imports:
  ```python
  _ALLOWED_LIFECYCLE_SOURCES: dict[AgentStatus, frozenset[AgentStatus]] = {
      AgentStatus.ACTIVE:  frozenset({AgentStatus.ACTIVE, AgentStatus.PAUSED, AgentStatus.STOPPED}),
      AgentStatus.PAUSED:  frozenset({AgentStatus.ACTIVE, AgentStatus.PAUSED, AgentStatus.STOPPED}),
      AgentStatus.STOPPED: frozenset({AgentStatus.ACTIVE, AgentStatus.PAUSED, AgentStatus.STOPPED}),
      # ARCHIVED is reachable only via delete_agent.
  }
  ```
- [ ] Modify `_transition_status` to read first, validate, then write:
  ```python
  async def _transition_status(self, agent_id: str, status: AgentStatus) -> AgentRecord:
      existing = await self.get_agent(agent_id)  # raises AgentNotFoundError if missing
      allowed = _ALLOWED_LIFECYCLE_SOURCES[status]
      if existing.status not in allowed:
          raise AgentInvalidStateTransitionError(
              f"transition to {status.value!r} not allowed from {existing.status.value!r}"
          )
      record = await self._repo.update_status(self._workspace_id, agent_id, status)
      if record is None:
          # Race window: existed at get, vanished under update. Treat as 404.
          raise AgentNotFoundError(f"agent not found: {agent_id!r}")
      return record
  ```
- [ ] Add `restore_agent`:
  ```python
  async def restore_agent(self, agent_id: str) -> AgentRecord:
      """Restore a soft-deleted agent. ARCHIVED → STOPPED only."""
      existing = await self.get_agent(agent_id)
      if existing.status != AgentStatus.ARCHIVED:
          raise AgentInvalidStateTransitionError(
              f"restore requires source state {AgentStatus.ARCHIVED.value!r}, "
              f"got {existing.status.value!r}"
          )
      try:
          record = await self._repo.update_status(
              self._workspace_id, agent_id, AgentStatus.STOPPED,
          )
      except _AgentNameConflictError as exc:
          # Restore would resurrect a name that was reused since archival.
          raise AgentNameConflictError(str(exc)) from exc
      if record is None:
          raise AgentNotFoundError(f"agent not found: {agent_id!r}")
      return record
  ```
  - Note: `AgentPersistence.update_status` does not currently raise `_AgentNameConflictError` because it does not touch the partial-unique index (it updates only `status`/`updated_at`). However, restoring from ARCHIVED to STOPPED moves the row back into the unique-index window, which CAN trigger a conflict if another agent has taken the name in the meantime. **Verification step:** read `update_status` SQL; if the constraint fires here, catch `IntegrityError` and re-raise `_AgentNameConflictError`. (See verification gate below.)
- [ ] Open `src/metatron/agents/__init__.py` and re-export `AgentInvalidStateTransitionError`.

### 3b — Persistence verification (no code change unless needed)

- [ ] **Verification gate:** read `src/metatron/agents/persistence.py:359-385` (`update_status`). It does plain `UPDATE agents SET status=:status WHERE id=:id AND workspace_id=:ws RETURNING …`. The partial-unique index is on `(workspace_id, name) WHERE status <> 'archived'`. Moving status from ARCHIVED → STOPPED inserts the row into the partial index. PostgreSQL will raise `UniqueViolation` if a non-archived row with the same `(workspace_id, name)` already exists.
- [ ] If `update_status` does not currently catch this: wrap the SQL call in try/except `IntegrityError` (SQLAlchemy) and raise `_AgentNameConflictError` to match the pattern in `save_new` and `update_with_version_bump`. Add this only if the failing case is not already covered by an existing test.
- [ ] If catch is added: extend the existing `tests/integration/agents/test_persistence.py` with a test reproducing the scenario.

### 3c — Route-layer changes

- [ ] Open `src/metatron/api/routes/agents.py`.
- [ ] Add `AgentInvalidStateTransitionError` to the import from `agents.service`.
- [ ] In each of `start_agent`, `stop_agent`, `pause_agent`, add the new exception arm:
  ```python
  except AgentInvalidStateTransitionError as exc:
      raise HTTPException(status_code=400, detail=str(exc)) from None
  ```
- [ ] Add new route after `pause_agent`:
  ```python
  @router.post("/{agent_id}/restore", response_model=AgentResponse)
  async def restore_agent(
      agent_id: str,
      user: Annotated[User, Depends(require_editor)],  # noqa: ARG001
      service: Annotated[AgentRegistryService, Depends(get_agent_registry_service)],
  ) -> AgentResponse:
      """Restore a soft-deleted agent: ARCHIVED → STOPPED. 400 if not archived."""
      try:
          record = await service.restore_agent(agent_id)
      except AgentNotFoundError as exc:
          raise HTTPException(status_code=404, detail=str(exc)) from None
      except AgentInvalidStateTransitionError as exc:
          raise HTTPException(status_code=400, detail=str(exc)) from None
      except AgentNameConflictError as exc:
          raise HTTPException(status_code=409, detail=str(exc)) from None
      return _agent_to_response(record)
  ```

### 3d — Test additions

- [ ] Open `tests/unit/test_agents_service.py`. Append a new `TestStateTransitionMatrix` class with 12 parametrized cases (3 source states {ACTIVE, PAUSED, STOPPED} × 3 verbs {start, stop, pause} = 9 success cases) plus 3 cases for source=ARCHIVED × 3 verbs (each → `AgentInvalidStateTransitionError`). Each case mocks `repo.get` to return a record with the source status, asserts service-layer outcome.
- [ ] Append a `TestRestore` class:
  - `test_restore_from_archived_returns_stopped` — happy path.
  - `test_restore_from_active_raises_invalid_transition` — assert `AgentInvalidStateTransitionError`.
  - `test_restore_from_stopped_raises_invalid_transition`.
  - `test_restore_missing_raises_not_found`.
- [ ] Open `tests/unit/test_agents_routes.py`. Append:
  - `test_start_archived_returns_400` — service raises `AgentInvalidStateTransitionError`, route maps to 400.
  - `test_restore_200_from_archived` — service returns STOPPED record, response_model validates.
  - `test_restore_400_when_not_archived`.
  - `test_restore_404_missing`.
  - `test_restore_viewer_forbidden_403`.
- [ ] **Verification gate:** `pytest tests/unit/test_agents_service.py tests/unit/test_agents_routes.py -v` — all green.

### 3e — Doc updates

- [ ] Open `src/metatron/agents/.claude/CLAUDE.md`. Replace the bullet starting `**Lifecycle is DB-only**` (lines 81-85 of v0) with:
  ```markdown
  - **Lifecycle is DB-only with state validation** — start/stop/pause flip
    the `status` flag (no version bump, no scheduler coupling). The service
    rejects lifecycle calls from the `ARCHIVED` source state with
    `AgentInvalidStateTransitionError` (HTTP 400). The only path out of
    `ARCHIVED` is `POST /api/v1/agents/{id}/restore`, which transitions
    `ARCHIVED → STOPPED`. State-transition matrix:

    | Source / Verb | start | stop | pause | restore | delete |
    |---|---|---|---|---|---|
    | ACTIVE   | 200 (no-op) | 200 | 200 | 400 | 204 |
    | PAUSED   | 200 | 200 | 200 (no-op) | 400 | 204 |
    | STOPPED  | 200 | 200 (no-op) | 200 | 400 | 204 |
    | ARCHIVED | 400 | 400 | 400 | 200 | 204 (no-op) |

    Hardened in MTRNIX-323; supersedes the earlier "lifecycle endpoints
    can un-archive" note.
  ```
- [ ] Open `docs/ROLLOUT_NOTES_2026-04-24.md`. Replace the "Agent Registry soft-delete semantics" stanza with one line: `Hardened in MTRNIX-323 — `/start|/stop|/pause` from ARCHIVED now return 400; new `POST /api/v1/agents/{id}/restore` (editor+) is the only path back. See CHANGELOG.`.
- [ ] Open `CHANGELOG.md`. Under `## [Unreleased]`, add `### Changed` (or extend the existing one) with:
  ```markdown
  - **breaking (REST):** `POST /api/v1/agents/{id}/start|stop|pause` on an
    `ARCHIVED` agent now returns 400 `AgentInvalidStateTransitionError`
    instead of un-archiving the agent. The new
    `POST /api/v1/agents/{id}/restore` (editor+) is the only transition
    out of ARCHIVED, and it lands in STOPPED — operators must explicitly
    `/start` afterwards. Per MTRNIX-319 §5, no live consumer was relying
    on the previous un-delete loophole. (MTRNIX-323)
  ```

## Phase 4 — Item 4: OAI-compat integration smoke

- [ ] Create directory `tests/integration/api/`.
- [ ] Create `tests/integration/api/__init__.py` (empty).
- [ ] Create `tests/integration/api/test_openai_compat_smoke.py` with the smoke test (see spec §"Item 4 — Test scope" for the body sketch).
  - Mocks `metatron.retrieval.search.hybrid_search_and_answer` to return a stub answer with `[$[Metatron Overview]$]` inline marker and a `Sources:` footer.
  - Asserts `200`, body contains `[Metatron Overview](https://example.com/overview)`, body contains `"Metatron"`.
  - Sends a Russian query in `messages[].content` to exercise non-ASCII path.
- [ ] **Verification gate:** `pytest tests/integration/api/test_openai_compat_smoke.py -v` — green.

## Phase 5 — Cross-item cleanup

- [ ] Open `docs/ROLLOUT_NOTES_2026-04-24.md`. Replace the remaining 3 "Known issues" stanzas (Event loop flake, Eval dataset v1.3, OAI-compat smoke) with one-line "Resolved in MTRNIX-323" notes.
- [ ] Open `CHANGELOG.md`. Under `## [Unreleased]`, ensure four entries exist:
  - `### Fixed` — eval driver event-loop reuse (MTRNIX-323 §1).
  - `### Changed` — eval dataset v1.3 → v1.4 (MTRNIX-323 §2).
  - `### Changed` — Agent Registry lifecycle (MTRNIX-323 §3, written in 3e).
  - `### Added` — OAI-compat integration smoke (MTRNIX-323 §4).

## Phase 6 — Final verification

- [ ] `pytest tests/unit/test_agents_service.py tests/unit/test_agents_routes.py tests/unit/test_openai_compat.py tests/integration/api/test_openai_compat_smoke.py tests/integration/agents/test_persistence.py -v` — all green.
- [ ] `make eval` (3 consecutive runs):
  - [ ] Each run emits `0` `qdrant.async.hybrid_search.fallback` events.
  - [ ] Each run completes cleanly with no `RuntimeError: Event loop is closed`.
- [ ] `make eval-compare` against the v1.4 baseline shows no regression > 0.01 on any positive metric.
- [ ] `grep -n "Known issues" docs/ROLLOUT_NOTES_2026-04-24.md` — section header still exists; the four sub-stanzas are now one-liners.
- [ ] `grep -n "POST /\\*/start.*archive\\|un-delete\\|un-archive" src/metatron/agents/.claude/CLAUDE.md` — empty.
- [ ] Architecture guard self-check:
  - [ ] No diff in `src/metatron/core/interfaces.py`.
  - [ ] No diff in `src/metatron/core/events.py`.
  - [ ] No new files under `src/metatron/storage/migrations/`.
  - [ ] No diff in `src/metatron/storage/migrations/`.
  - [ ] All workspace_id usage in modified files is unchanged or strictly tighter.

## Phase 7 — PR

- [ ] Stage code + tests + dataset + docs.
- [ ] Commit per item or as one bundle (your call) with messages of the form `feat(MTRNIX-323): …` / `fix(MTRNIX-323): …` / `docs(MTRNIX-323): …`. **No `Co-Authored-By`, no Claude Code badge** (per ticket rules).
- [ ] Push the branch, open PR titled `MTRNIX-323: pre-rollout follow-ups (eval infra, dataset v1.4, agent registry restore, OAI smoke)`.
- [ ] PR description includes the four AC checkmarks from the spec §"Success Criteria".
```

