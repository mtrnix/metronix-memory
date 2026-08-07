# Community Issue Drafts

Fifteen issue-ready drafts for the Metronix backlog. Each item includes a clear title, project context, acceptance criteria, and a difficulty label so it can be copied into GitHub with minimal editing.

## Good First Issue

### 1. Docs: fix stale repo links and contribution references

**Suggested labels:** `good first issue`, `documentation`
**Difficulty:** `easy`

**Context**
`CONTRIBUTING.md` still links to `mtrnix/metronixcore` for labels and discussions, while this repo is `mtrnix/metronix-memory`. This is a small but visible paper cut for new contributors and makes issue discovery harder.

**Acceptance criteria**
- Audit `README.md`, `CONTRIBUTING.md`, and `.github` templates for stale repo-name links or legacy references.
- Update broken or outdated URLs so they point at the current repository and the correct labels/discussions pages.
- Keep wording and structure unchanged unless needed to fix correctness.
- Add or update a small regression note in the PR description listing the links that were corrected.

### 2. Example: add a JavaScript/TypeScript SDK quickstart

**Suggested labels:** `good first issue`, `documentation`, `examples`
**Difficulty:** `easy`

**Context**
The docs index already includes Python and Go SDK guidance, but there is no equivalent quickstart for JavaScript or TypeScript users. That is a common adoption path for agent builders using Node runtimes.

**Acceptance criteria**
- Add a new guide under `docs/integrations/` or `docs/examples/` for JavaScript/TypeScript usage.
- Cover the simplest useful flow: health check, one chat call to `/v1`, and one MCP or REST example for memory/search.
- Match the structure used in `docs/integrations/sdk-python.md` and the integration template in `CONTRIBUTING.md`.
- Link the new guide from `docs/README.md`.

### 3. Connector polish: support `google_drive` as an alias for `gdrive`

**Suggested labels:** `good first issue`, `connectors`, `frontend`
**Difficulty:** `easy`

**Context**
The backend registry currently registers `gdrive` in `src/metronix/connectors/registry.py`, while the frontend connection dialog already uses `google_drive` in its icon/color maps. Supporting the more explicit alias would reduce connector-name confusion in UI and docs.

**Acceptance criteria**
- Allow `google_drive` anywhere `gdrive` is currently accepted for connection creation or schema lookup.
- Preserve backward compatibility for existing `gdrive` users.
- Update any affected docs or examples so both names are not presented inconsistently.
- Add unit coverage for alias registration or normalization behavior.

### 4. Tests: add focused coverage for `metronix_memory_get_context`

**Suggested labels:** `good first issue`, `tests`, `mcp`
**Difficulty:** `easy`

**Context**
`src/metronix/mcp/tools/memory_context.py` is a high-value MCP surface used by agent runtimes, and it has several branches worth pinning down: invalid agent IDs, blank queries, feature-flag-off behavior, and default `memory_top_k` handling.

**Acceptance criteria**
- Add unit tests for invalid params and blank-input error responses.
- Add a test for the early-return path when `memory_injection_enabled` is disabled.
- Add a test proving `memory_top_k` falls back correctly when omitted.
- Keep the tests isolated and avoid requiring external services.

### 5. Config UX: surface more useful public config to the frontend

**Suggested labels:** `good first issue`, `frontend`, `config`
**Difficulty:** `easy`

**Context**
`/api/v1/config` currently only returns installed plugin names from `src/metronix/api/routes/config.py`. The frontend could make better setup decisions if the endpoint exposed a little more safe public metadata, such as available connector types or feature flags intended for UI gating.

**Acceptance criteria**
- Extend the public config payload with at least one additional safe, non-secret field that improves frontend setup UX.
- Use the new field in the frontend to improve a visible setup or connection flow.
- Do not expose credentials, internal URLs, or anything environment-sensitive.
- Add unit coverage for the API response shape and the frontend behavior if applicable.

## Help Wanted: Medium Integrations

### 6. Integration: add a LangGraph guide and runnable memory example

**Suggested labels:** `help wanted`, `integrations`, `langgraph`
**Difficulty:** `medium`

**Context**
Metronix already documents LangChain, but many teams now build agent workflows directly on LangGraph. A first-class guide should show how to combine Metronix MCP memory tools or the OpenAI-compatible endpoint with graph state and stable agent IDs.

**Acceptance criteria**
- Add `docs/integrations/langgraph.md` following the project’s integration-guide template.
- Include one runnable example under `examples/` that demonstrates stable `agent_id`, workspace scoping, and at least one memory retrieve/store step.
- Document when to use MCP versus `/v1` for LangGraph flows.
- Link the guide from `README.md` and `docs/README.md`.

### 7. Integration: add a CrewAI guide and example crew with shared memory policy

**Suggested labels:** `help wanted`, `integrations`, `crewai`
**Difficulty:** `medium`

**Context**
CrewAI is a common orchestration layer for multi-role agents, and Metronix’s agent-scoped memory model is a strong fit. What is missing is guidance on stable IDs, per-role memory boundaries, and shared workspace usage.

**Acceptance criteria**
- Add a CrewAI integration guide under `docs/integrations/`.
- Include an example crew showing at least two roles and a documented memory-scoping strategy.
- Show how to verify memory retrieval per role without leaking state between agent IDs.
- Include troubleshooting for bad agent-ID hygiene and workspace mix-ups.

### 8. Integration: add an AutoGen guide for tool-driven memory workflows

**Suggested labels:** `help wanted`, `integrations`, `autogen`
**Difficulty:** `medium`

**Context**
AutoGen users often want explicit tool calls, which maps naturally to Metronix MCP tools like status, memory search, memory store, and source sync. A guide should explain the recommended tool-first integration path rather than only chat completions.

**Acceptance criteria**
- Add `docs/integrations/autogen.md`.
- Provide a minimal example that calls Metronix through MCP or a thin wrapper around MCP-equivalent HTTP calls.
- Explain how to pass `Authorization` and `X-Agent-Id` consistently.
- Include a short verification sequence that proves the agent can store and later retrieve memory.

### 9. Integration: add a LlamaIndex guide for retrieval plus durable memory

**Suggested labels:** `help wanted`, `integrations`, `llamaindex`
**Difficulty:** `medium`

**Context**
LlamaIndex users care about retrieval composition, and Metronix already offers dense, sparse, graph, and freshness-aware retrieval layers. The guide should position Metronix as a memory and retrieval backend rather than duplicating an in-process index.

**Acceptance criteria**
- Add `docs/integrations/llamaindex.md`.
- Include a runnable example that uses Metronix as the retrieval or memory layer in a LlamaIndex workflow.
- Explain how Metronix’s hybrid retrieval differs from a default local vector index.
- Document at least one verification step that inspects grounded results or returned citations.

### 10. Integration: add an OpenAI Agents SDK guide and end-to-end example

**Suggested labels:** `help wanted`, `integrations`, `openai agents sdk`
**Difficulty:** `medium`

**Context**
The repo already supports MCP-native agent flows and an OpenAI-compatible API, which makes it a natural fit for the OpenAI Agents SDK. A dedicated guide would help users choose between tool-based memory access and chat-surface integration.

**Acceptance criteria**
- Add `docs/integrations/openai-agents-sdk.md`.
- Include an example that uses a stable agent identity and demonstrates at least one memory-aware turn.
- Explain when to reach for MCP tools versus the OpenAI-compatible `/v1` endpoint.
- Add setup, verify, and troubleshooting sections consistent with the existing integration docs.

## Research / Advanced

### 11. Research: build a freshness-policy tuning workflow

**Suggested labels:** `research`, `freshness`, `help wanted`
**Difficulty:** `advanced`

**Context**
Metronix has a substantial freshness pipeline across `src/metronix/freshness/`, `src/metronix/memory/freshness/`, and `src/metronix/ingestion/freshness/`, plus many policy knobs in `src/metronix/core/config.py`. What is missing is a repeatable workflow for tuning thresholds and aging policies against an evaluation set instead of by intuition.

**Acceptance criteria**
- Define a reproducible tuning workflow for at least linker, reconciler, or stale-after thresholds.
- Add a script or harness that can run policy sweeps and emit comparable metrics.
- Document the evaluation inputs, output metrics, and how to interpret tradeoffs.
- Keep the implementation additive and gated so it does not alter production defaults by accident.

### 12. Research: add a graph-context ablation mode to retrieval evaluation

**Suggested labels:** `research`, `retrieval`, `graph`
**Difficulty:** `advanced`

**Context**
Metronix positions graph context as a core retrieval signal, but the repo lacks a clean ablation path that answers “how much does graph context help on this workload?” This would make benchmark claims sharper and help guide future graph investment.

**Acceptance criteria**
- Add a flag or evaluation mode that can disable graph-context contribution without breaking the rest of retrieval.
- Ensure the ablation can be run through an existing benchmark or evaluation entry point.
- Emit side-by-side metrics comparing baseline versus graph-disabled retrieval.
- Document any caveats, especially if graph removal changes ranking, token budget, or citation behavior.

### 13. Research: evaluate SPLADE versus dense weighting across query classes

**Suggested labels:** `research`, `retrieval`, `splade`
**Difficulty:** `advanced`

**Context**
The codebase already contains SPLADE support, dense retrieval, adaptive RRF, and query-class weighting logic across `src/metronix/ingestion/splade.py`, `src/metronix/retrieval/channels.py`, and `src/metronix/retrieval/query_classifier.py`. A structured study would help decide whether current dense/sparse defaults are well calibrated.

**Acceptance criteria**
- Build or extend a sweep that varies dense and sparse weighting across at least several query categories.
- Report results in a compact artifact such as Markdown or CSV with enough detail to compare settings.
- Include an explicit recommendation on whether defaults should change, remain as-is, or become query-class-specific.
- Do not silently change runtime defaults as part of the first PR; measurement comes first.

### 14. Research: create a unified memory-eval harness for regression testing

**Suggested labels:** `research`, `benchmarks`, `memory`
**Difficulty:** `advanced`

**Context**
The repo already has benchmark pieces under `benchmarks/longmemeval/`, `scripts/run_eval.py`, `scripts/rag_eval_397.py`, and fixtures under `src/metronix/benchmarker/fixtures/`. What is missing is a single harness for repeatable memory regression runs that contributors can use before and after retrieval or memory changes.

**Acceptance criteria**
- Design a single entry point that can run at least two existing memory or retrieval evaluation flows with a consistent output format.
- Emit machine-readable results suitable for diffing in CI or local experiments.
- Document required environment setup, expected runtime, and how to interpret pass/fail or regression thresholds.
- Keep the first version pragmatic; it can wrap existing scripts rather than fully replacing them.

### 15. Research: formalize multi-agent scoping and leakage tests

**Suggested labels:** `research`, `agents`, `security`, `memory`
**Difficulty:** `advanced`

**Context**
Agent and workspace scoping are a core product promise, and the repo already has some isolation coverage in memory, API, and integration tests. A dedicated research issue should map the remaining leakage surface for multi-agent runtimes and produce a stronger test matrix for shared-workspace deployments.

**Acceptance criteria**
- Identify the main scoping dimensions to test: agent ID, workspace ID, shared source access, and memory retrieval boundaries.
- Add or extend tests that exercise both allowed sharing and forbidden leakage paths.
- Produce a short design note summarizing where scoping is enforced today and where it is only implied.
- Call out any open questions around shared crew or orchestrator patterns so follow-up issues can be split cleanly.
