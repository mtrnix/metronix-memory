# Pre-rollout follow-ups — Design

**Date:** 2026-04-25
**Jira:** MTRNIX-323 — Pre-rollout follow-ups (eval infra, dataset hygiene, Agent Registry UX, optional smoke).
**Depends on:** MTRNIX-316 (merged), MTRNIX-319 (validation gate, merged), MTRNIX-322 (merged).
**Parent ticket / context:** `docs/ROLLOUT_NOTES_2026-04-24.md` "Known issues" — all four items.
**Author:** Architect (agent-team)
**Status:** Draft — ready for implementation plan

## Goal

Close the four loose ends that MTRNIX-319 left as "Known issues" in the rollout
note. None are blockers for the consuming team's first integration; closing
them now is cheap and removes documented quirks before any external client
codifies them.

The four items are independent — they touch the eval driver (script-level),
a YAML fixture, the Agent Registry REST surface, and a single integration
test file. There is no shared state and no ordering between them.

## Non-goals

- **Refactoring `_async_hybrid_stores` cache invalidation strategy.** The
  module-level singleton is correct for production where one event loop runs
  for the lifetime of the process. The bug is purely in the eval driver
  re-entering `asyncio.run()`. Touching production cache semantics is out of
  scope.
- **Redesigning the eval test set.** Item 2 is a surgical pass over the
  temporal/status queries that drifted; the v1.3 → v1.4 bump is a hygiene
  pass, not a methodology change. Adding new categories (recall@K bins,
  multi-hop graph queries, etc.) is a separate ticket.
- **Full state-machine library for agent lifecycle.** The Agent Registry has
  four statuses and a small, fixed transition table. A hand-coded matrix in
  `_transition_status` is sufficient and matches the existing code style.
  No `transitions`/`statemachine` library introduction.
- **OAI-compat live load test.** Item 4 explicitly scopes to ONE smoke test
  with mocked `hybrid_search_and_answer`. The intent is contract validation,
  not RAG quality measurement.
- **MCP-side agent endpoints.** `docs/MCP_API.md` does not expose agent
  registry tools today; this ticket leaves MCP untouched. If MCP exposes
  agent tooling later, the new state-transition matrix carries through
  unchanged.
- **Migration to async-from-the-start in `scripts/run_eval.py`.** The eval
  CLI stays synchronous on the outside; only the inner search invocation
  becomes a single `asyncio.run`.

## Constraints

- **Layer boundaries.** Item 1 lives in `scripts/` (no `src/metatron` change
  beyond verification that `clear_store_cache()` exists — it does, at
  `storage/qdrant.py:1191`). Item 2 is a YAML fixture only. Item 3 adds one
  typed error in `agents/service.py` (L3) and one route in
  `api/routes/agents.py` (L6). Item 4 is a test file only. **No imports
  cross layer boundaries.**
- **No `core/interfaces.py`, `core/events.py`, `core/models.py` change.** Confirmed.
- **No migrations.** Item 3 reads `agents.status` and writes the same column
  with a new pre-condition; the column already exists (added in MTRNIX-270).
- **Workspace isolation.** Item 3's new `restore_agent` reads and writes by
  `(workspace_id, agent_id)` — same pattern as `delete_agent`.
- **RBAC.** New `/restore` endpoint is `editor+` — same gate as `/start`.
- **Backwards compatibility.** Item 3 IS a contract change: `POST /start`
  on an archived agent shifts from `200 + status=active` to `400 +
  AgentInvalidStateTransitionError`. Per MTRNIX-319 §5, no live consumer
  has integrated yet. Documented in `CHANGELOG.md ### Changed` under the
  next release.
- **Architecture guard:** repo is metatron-core; all four items stay inside
  it; no enterprise/control-center spillover.

## Item 1 — eval event-loop flake

### Root cause

`scripts/run_eval.py` calls `hybrid_search_and_answer_sync(...)` once per
positive query and once per negative query (29 calls total in v1.3).
`hybrid_search_and_answer_sync` (`retrieval/search.py:1220-1243`) is a thin
`asyncio.run(hybrid_search_and_answer(...))` wrapper. Each `asyncio.run`
creates a fresh event loop, runs the coroutine, and closes the loop on exit.

Inside the coroutine, `recall_dense_async` (`retrieval/channels.py:321`)
fetches the cached `AsyncQdrantVectorStore` via `get_async_hybrid_store(ws)`
(`storage/qdrant.py:1205`). The cache `_async_hybrid_stores` is a
module-level dict. The first call stores an `AsyncQdrantVectorStore` whose
underlying `AsyncQdrantClient` is bound to that first event loop's
networking transport. When `asyncio.run` returns, the loop is closed but
the cached client is not — its `_async_hybrid_stores` entry survives.

Subsequent queries (calls 2..29) hit the same cached client; its underlying
HTTPX/AsyncQdrant transport tries to use the now-closed loop, raising
`RuntimeError: Event loop is closed`. The `try/except` at
`storage/qdrant.py:855-861` catches this and falls back to dense-only
search — emitting `qdrant.async.hybrid_search.fallback`. The ticket's
deterministic 8-out-of-29 reproduction count matches: 8 queries are the
first ones in their respective recall channels to dispatch a fresh await
on the bound client (the others reuse intermediate state already drained
into the dense fallback path).

### Decision: fix (b) — single `asyncio.run` with shared client

**Confirm fix (b) over (a).** Rationale:
- Per-query instantiation (a) defeats the cached-singleton optimisation
  in production code paths the eval drives — i.e. it is structurally
  divergent from how the system runs in prod. The eval would no longer
  exercise the same client lifecycle as a real workload.
- Single `asyncio.run` (b) collapses 29 loop creations to one, reuses the
  cached client across all 29 queries inside the same loop, and matches
  what a real long-running consumer (FastAPI, MCP server, freshness
  worker) does — 1 loop per process, many calls.
- Implementation cost is identical; (b) is also marginally faster
  (no 29× loop teardown).

### Surgery site

`scripts/run_eval.py:run_eval()` (lines 76-213). Convert to async, drive
the per-query loops with `await hybrid_search_and_answer(...)` directly,
then call once via `asyncio.run(run_eval(...))` from `main()`.

Crucial preamble: call `clear_store_cache()` immediately before the
`asyncio.run` to flush any stray client an import-time side-effect may have
parked in the cache. This makes the eval reproducible regardless of
whether anything else in the process touched Qdrant before `run_eval`.

```python
# scripts/run_eval.py — sketch
from metatron.storage.qdrant import clear_store_cache
from metatron.retrieval.search import hybrid_search_and_answer

async def run_eval(workspace, k, testset_path, *, include_unstable=False) -> dict:
    ts = load_eval_testset_from_path(testset_path)
    rm = RetrievalMetrics()
    queries = ts.queries if include_unstable else [q for q in ts.queries if q.stable]
    ...
    for q in positive_queries:
        trace = await hybrid_search_and_answer(
            q.text, workspace, k, None, None, return_trace=True,
        )
        ...
    ...
    return result

def main() -> None:
    args = ...parser.parse_args()
    if args.history:
        show_history()
        return
    clear_store_cache()
    results = asyncio.run(run_eval(args.workspace, args.k, testset_path,
                                   include_unstable=args.all))
    ...
```

The `hybrid_search_and_answer` async signature already supports being
awaited directly (`retrieval/search.py:802`). No production code changes.

### Acceptance criteria

- Three consecutive `make eval` runs emit **0** `qdrant.async.hybrid_search.fallback`
  events. Validated by `grep -c qdrant.async.hybrid_search.fallback` on the
  eval logs from each run.
- Eval wall-time non-regression (informational): expect ~1 s improvement
  from collapsed loop teardown; not a hard gate.
- Aggregate metric values may shift modestly upward as the 8 previously-
  degraded queries now use full hybrid retrieval. This is the intended
  effect, not a regression. Plan calls out re-baselining `eval_results/`.

## Item 2 — dataset hygiene (v1.3 → v1.4)

### Audit (each query checked against current Jira state)

| id | Current expected | Jira state today | Action |
|---|---|---|---|
| `exec-02` "What tasks are currently in progress?" | `MTRNIX-255`, `MTRNIX-224`, `MTRNIX-164` | All `Done` | **Rewrite (a)** |
| `time-01` "What tickets were created this month?" | `MTRNIX-255`, `MTRNIX-253`, `MTRNIX-254` | All `Done`, all created late March 2026 — "this month" is now April | **Rewrite (a)** |
| `time-03` "What happened with the MCP client recently?" | `MTRNIX-125`, `MTRNIX-35` | "recently" wobbles month-to-month | **Rewrite (a)** |
| `time-05` "What was done last sprint?" | `MTRNIX-255`, `MTRNIX-224`, `MTRNIX-253` | Sprint identity not in retrievable payload | **Mark `stable: false`** |
| `agg-01` "How many tasks are in the current sprint?" | `MTRNIX-255`, `MTRNIX-224`, `MTRNIX-253` | Same as `time-05` | **Mark `stable: false`** |
| `ru-02` (Russian mirror of `exec-02`) | Same three tickets | Same drift | **Rewrite (a)** to match `exec-02` |
| `time-02` "latest update on RBAC" | `3836625`, `MTRNIX-104`, `MTRNIX-154` | Expected docs are stable Confluence + done tickets; "latest" doesn't bind to a moving target | **Keep** |
| `time-04` "documentation updated in 2026" | Stable Confluence pages | Year-anchored, expected set unchanged | **Keep** |

### Final v1.4 query texts (rewrites)

- `exec-02`: `"What tickets describe Hermes integration and standup workflows?"`
  - expected: `MTRNIX-255` (Hermes daily meeting artifacts), `MTRNIX-224` (Hermes-native standup MCP integration). Drop `MTRNIX-164` (search-quality epic, only loosely on-topic).
- `time-01`: `"What tickets cover Hermes-native standup setup and demo prep?"`
  - expected: `MTRNIX-255`, `MTRNIX-253` (demo prep), `MTRNIX-254` (demo data). Topic-anchored, not month-anchored.
- `time-03`: `"What documents and tickets describe the MCP client integration?"`
  - expected: `MTRNIX-125`, `MTRNIX-35`. No "recently" decorator.
- `ru-02` (Russian mirror): `"Какие тикеты описывают интеграцию Hermes и standup-процессы?"`
  - expected: `MTRNIX-255`, `MTRNIX-224`. Mirrors the new `exec-02`.

Notes columns updated; `notes:` prefix becomes `topic-anchored — see MTRNIX-323`.

### `stable: false` marks

- `time-05` and `agg-01` get `stable: false` plus `notes: "sprint-identity query, requires sprint metadata in retrievable payload — re-enable after sprint-aware retrieval lands"`.

### Header bumps

- `version: "1.4"`.
- `description` last line: `Last updated 2026-04-25 (v1.4: temporal/status queries de-pinned to semantic markers and sprint-anchored queries marked unstable — MTRNIX-323).`.

### Aggregate-tolerance verification

`scripts/run_eval.py:87` already filters `q.stable` so `stable: false` queries
don't enter `pairs[]` → don't enter `compute_averages` → don't shift
P@10/MRR/NDCG@10. Verified by reading the script. Re-baseline note: after
the fix lands, the coder runs `make eval-save` once so subsequent
`make eval-compare` deltas are measured against v1.4 baseline.

### Acceptance criteria

- Post-fix eval aggregate is within ±0.01 of pre-fix on the queries that
  remain in v1.4 (i.e. excluding the two newly-unstable items, which are
  also excluded pre-fix). Mechanism: rewrites move four queries from
  P@10=0 to P@10>0 (or unchanged); the average can only stay the same or
  improve. The two `stable: false` marks change the denominator on both
  sides equally and net to zero on the average.
- The four rewritten queries return at least one expected doc each on a
  fresh eval run (positive sanity).

## Item 3 — Agent Registry state-transition hardening

### Decision: option (b) — reject `start` from `ARCHIVED`, add `/restore`

Rationale:
- (a) "keep + document" leaves a documented un-delete loophole on a public
  REST endpoint that the consuming team has not yet integrated. Today is
  the cheapest possible moment to fix it (zero deprecation cost).
- (c) "DELETE → CREATE for fresh agents" loses the recoverable-soft-delete
  audit trail. The 5-role RBAC roadmap (target: Agent Admin) almost
  certainly wants explicit `restore` semantics; adding the endpoint now
  pre-aligns with that roadmap.
- (b) is small and surgical: one new typed error, one new endpoint, one
  pre-condition check in the service layer.

The current caveat in `src/metatron/agents/.claude/CLAUDE.md` lines 81-85
("`POST /start` on an archived agent transitions it back to ACTIVE") is
**superseded** by this decision and is replaced with the matrix below.

### State-transition matrix

| Current → | `start` | `stop` | `pause` | `restore` | `delete` |
|---|---|---|---|---|---|
| `ACTIVE`   | 200 (no-op) | 200 → STOPPED | 200 → PAUSED | **400** | 204 → ARCHIVED |
| `PAUSED`   | 200 → ACTIVE | 200 → STOPPED | 200 (no-op) | **400** | 204 → ARCHIVED |
| `STOPPED`  | 200 → ACTIVE | 200 (no-op) | 200 → PAUSED | **400** | 204 → ARCHIVED |
| `ARCHIVED` | **400** | **400** | **400** | 200 → STOPPED | 204 (no-op) |

Notes:
- Idempotent verbs (start on already-ACTIVE, stop on already-STOPPED,
  pause on already-PAUSED, delete on already-ARCHIVED) return 200/204
  with the existing record. Retry-friendly.
- `restore` is the **only** path out of ARCHIVED.
- `restore` always lands in `STOPPED` (matching the `create_agent`
  default), never directly in ACTIVE — the operator must explicitly
  `POST /start` after restore. This prevents accidental traffic
  re-routing from a confused un-delete.

### New error class

```python
# src/metatron/agents/service.py
class AgentInvalidStateTransitionError(MetatronError):
    """Requested lifecycle transition is not allowed from the current status."""
```

Re-exported via `agents/__init__.py`.

### Service-layer changes (`src/metatron/agents/service.py`)

`_transition_status` becomes pre-condition aware. New private constant:

```python
_ALLOWED_LIFECYCLE_SOURCES: dict[AgentStatus, frozenset[AgentStatus]] = {
    AgentStatus.ACTIVE:  frozenset({AgentStatus.ACTIVE, AgentStatus.PAUSED, AgentStatus.STOPPED}),
    AgentStatus.PAUSED:  frozenset({AgentStatus.ACTIVE, AgentStatus.PAUSED, AgentStatus.STOPPED}),
    AgentStatus.STOPPED: frozenset({AgentStatus.ACTIVE, AgentStatus.PAUSED, AgentStatus.STOPPED}),
    # ARCHIVED is reachable only via delete_agent; never via _transition_status.
}
```

`_transition_status` flow: read existing record (404 if missing) → check
`existing.status` is in `_ALLOWED_LIFECYCLE_SOURCES[target]` → raise
`AgentInvalidStateTransitionError` if not → call `repo.update_status(...)`
as today.

New method:

```python
async def restore_agent(self, agent_id: str) -> AgentRecord:
    """Restore a soft-deleted agent. ARCHIVED → STOPPED only."""
    existing = await self.get_agent(agent_id)
    if existing.status != AgentStatus.ARCHIVED:
        raise AgentInvalidStateTransitionError(
            f"restore requires source state ARCHIVED, got {existing.status.value!r}"
        )
    record = await self._repo.update_status(self._workspace_id, agent_id, AgentStatus.STOPPED)
    if record is None:
        raise AgentNotFoundError(f"agent not found: {agent_id!r}")
    return record
```

`delete_agent` is unchanged (always allowed).

### Route-layer changes (`src/metatron/api/routes/agents.py`)

Add 400 mapping to all four lifecycle routes (`/start`, `/stop`, `/pause`,
new `/restore`):

```python
except AgentInvalidStateTransitionError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from None
```

New route:

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
    return _agent_to_response(record)
```

### Doc updates

- `src/metatron/agents/.claude/CLAUDE.md` — replace the "Lifecycle is DB-only"
  bullet (lines 81-85) with the new matrix and a one-line description of
  `/restore`.
- `CHANGELOG.md` — `### Changed` entry under `[Unreleased]`:
  > **Breaking (REST):** `POST /api/v1/agents/{id}/start|stop|pause` on an
  > `ARCHIVED` agent now returns 400 `AgentInvalidStateTransitionError`
  > instead of un-archiving the agent. Use the new
  > `POST /api/v1/agents/{id}/restore` (editor+) to move
  > `ARCHIVED → STOPPED` and then `/start` it explicitly. (MTRNIX-323)
- `docs/ROLLOUT_NOTES_2026-04-24.md` — replace the "Agent Registry
  soft-delete semantics" stanza with a one-line "Resolved in MTRNIX-323;
  see CHANGELOG."

### Acceptance criteria

- New service unit tests cover all 16 cells of the lifecycle×status
  matrix (4 lifecycle verbs × 4 source states; restore included).
- New route tests cover: `/start` from ARCHIVED → 400; `/restore` from
  ARCHIVED → 200 + status==STOPPED; `/restore` from non-ARCHIVED → 400;
  `/restore` 404 on missing; `/restore` viewer → 403.
- The existing `DELETE /{id}` then `GET /{id}` returning 200 with archived
  record stays green (no change to that contract).
- The existing `delete_agent` test stays green.
- `agents/.claude/CLAUDE.md` no longer references the un-delete loophole.

## Item 4 — OAI-compat smoke test

### Decision: add ONE integration smoke test

Rationale: 13 unit tests already cover individual code paths in
`tests/unit/test_openai_compat.py`. The unit tests do not catch
"`create_app` wiring drift" or "`hybrid_search_and_answer` returning
something the OAI body builder can't parse". Both are operator-facing
failure modes that an integration test catches in ~50 LoC. Out-of-scope
treatment leaves a known regression vector on a public surface; the
asymmetry of cost (one test) vs. blast radius (every OAI consumer) is too
favourable to skip.

### Test scope

File: `tests/integration/api/test_openai_compat_smoke.py` (new).
Sibling `__init__.py` for `tests/integration/api/`.

```python
# Sketch
def test_chat_completions_smoke_returns_200_with_citations(monkeypatch):
    settings = Settings(
        METATRON_ENV="test",
        DEFAULT_WORKSPACE_ID="MTRNIX",
        DEFAULT_WORKSPACE_NAME="MTRNIX",
        METATRON_OPENAI_COMPAT_ENABLED=True,
        METATRON_OPENAI_COMPAT_KEY="test-key",
    )
    # Mock the live RAG call — smoke validates the envelope, not RAG quality.
    async def _fake_search(**kwargs):
        return (
            "Metatron is intelligent memory infrastructure for AI agents "
            "[$[Metatron Overview]$].\n\n---\nSources:\n"
            "📄 Metatron Overview \u2014 https://example.com/overview"
        )
    monkeypatch.setattr(
        "metatron.retrieval.search.hybrid_search_and_answer", _fake_search,
    )
    app = create_app(settings)
    client = TestClient(app, raise_server_exceptions=False)

    r = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "metatron-rag-MTRNIX",
            "messages": [{"role": "user", "content": "Что такое Метатрон?"}],
        },
    )
    assert r.status_code == 200
    body = r.json()["choices"][0]["message"]["content"]
    # Citation rendering — markdown link present
    assert "[Metatron Overview](https://example.com/overview)" in body
    # Non-ASCII path didn't crash + the answer body survived intact
    assert "Metatron" in body
```

### Acceptance criteria

- Test passes against the unmodified `routes/openai_compat.py`. (It must,
  because no code change is required for item 4 — this is purely an
  observability gain.)
- Test sits in `tests/integration/api/` to keep `tests/unit/` boundary
  clean (full app factory invocation is integration-grade).
- Rollout note's "Optional: OAI-compat smoke" stanza removed; replaced
  with a one-line "Integration smoke: `tests/integration/api/test_openai_compat_smoke.py`."

## Cross-item: rollout note + CHANGELOG

`docs/ROLLOUT_NOTES_2026-04-24.md`:
- "Event loop flake" stanza → "Resolved in MTRNIX-323."
- "Eval dataset v1.3 — temporal queries still pinned" → "Resolved in
  MTRNIX-323; dataset bumped to v1.4."
- "Agent Registry soft-delete semantics" → "Hardened in MTRNIX-323;
  `/restore` endpoint added; see CHANGELOG."
- "Optional: OAI-compat smoke" → "Smoke covered by
  `tests/integration/api/test_openai_compat_smoke.py`."

`CHANGELOG.md` under `[Unreleased]`:
- `### Fixed` — eval driver event-loop reuse (MTRNIX-323 §1).
- `### Changed` — eval dataset v1.3 → v1.4 (MTRNIX-323 §2).
- `### Changed` — Agent Registry: lifecycle from ARCHIVED rejected with
  400; `/restore` endpoint added (MTRNIX-323 §3).
- `### Added` — OAI-compat integration smoke test (MTRNIX-323 §4).

## Risks

- **Risk 1: eval re-baseline confuses next reviewer.** The first
  `make eval-compare` after the fix will show metric drift because the 8
  previously-degraded queries now run full hybrid. **Mitigation:** plan
  step explicitly calls for `make eval-save` post-fix and a CHANGELOG note
  documenting the expected upward shift.
- **Risk 2: a cached `_async_hybrid_stores` entry in some forgotten code
  path violates the eval's reset.** **Mitigation:** the eval calls
  `clear_store_cache()` immediately before `asyncio.run`. If a future code
  path adds a parallel cache, it owns its own reset story.
- **Risk 3: route-test coverage misses one matrix cell.** **Mitigation:**
  spec calls out 16-cell matrix coverage explicitly; plan checklist
  enumerates each cell.
- **Risk 4: an external client already retries `DELETE → /start`.** Per
  MTRNIX-319 §5 the consuming team has not integrated. **Mitigation:**
  CHANGELOG `### Changed` entry is unambiguous.

## Success Criteria

1. `make eval` produces 0 fallback log events on three consecutive runs.
2. v1.4 dataset checked in, baseline re-saved, `make eval-compare` shows
   no regression on the queries that exist in both v1.3 and v1.4.
3. `/api/v1/agents/{id}/restore` exists, returns 200 from ARCHIVED, 400
   from any other state. `/start` from ARCHIVED returns 400. State-machine
   matrix covered by tests.
4. `tests/integration/api/test_openai_compat_smoke.py` passes.
5. `docs/ROLLOUT_NOTES_2026-04-24.md` no longer lists any of the four as
   "Known issues".
6. `agents/.claude/CLAUDE.md` no longer documents the un-delete loophole.
7. CHANGELOG `[Unreleased]` carries one entry per item.
```

---

## Deliverable 2 — `docs/superpowers/plans/2026-04-25-pre-rollout-followups.md`

Full Markdown body to write to that path:

