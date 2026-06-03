# RAG Debug Trace — Frontend Reference

## What it is and why

The backend records a **full trace of every RAG request** — everything that happened from the
user's message to the final answer: query rewriting, classification, what each recall channel found
with scores, what the reranker kept, the exact prompt sent to the LLM, and the raw vs. final answer.

**Purpose of the page:** debug "strange sources" and "nonsense answers". The user takes a `trace_id`
(it arrives as a footer in the answer itself — see below), opens the page, and sees step by step why
a given document ended up in the answer and what actually went into the model.

**Where the `trace_id` comes from:** every assistant answer gets a footer `\n\n— trace: <uuid>`.
Parse it like this:

```ts
const m = answer.match(/—\s*trace:\s*([0-9a-f-]{36})/i);
const traceId = m?.[1] ?? null;
// to display the answer without the tail:
const clean = answer.replace(/\n*—\s*trace:\s*[0-9a-f-]{36}\s*$/i, "");
```

---

## Endpoints

Base: `/api/v1/traces`. **Auth: JWT Bearer** (same as `/memory`, `/knowledge`, `/agents`) — i.e.
`require_viewer`. The OpenAI-compat key (`mtk_…` / `metatron-test-key`) does **not** work here; a
normal login token is required. Workspace is taken from the token; you may optionally pass
`?workspace_id=<id>` (access-checked against the token, else 403).

### 1. Trace detail
```
GET /api/v1/traces/{trace_id}
```
- **200** → a `RagTrace` object (see interface below).
- **404** → not found OR belongs to another workspace (isolation).
- **422** → `trace_id` is not a valid UUID.
- **401** → missing/invalid Bearer token.
- Reads are **not** gated by the `METATRON_RAG_TRACE_ENABLED` flag — historical traces are always readable.

### 2. Recent traces list
```
GET /api/v1/traces/?limit=20&offset=0
```
- **Note the trailing slash** — the API runs with `redirect_slashes=False`, so when calling it
  directly the slash is required (same as `/api/v1/agents/`). Through the CC UI proxy both
  `/api/v1/traces` and `/api/v1/traces/` work (nginx normalises the bare path).
- `limit` 1..100 (default 20), `offset` 0..10000.
- **200** → `RagTraceListResponse` (lightweight rows, no heavy JSONB — for a table/feed).

---

## Full interface (TypeScript)

> Every field below is actually present in a recorded trace (verified on live records). Numbers are
> JSON numbers, ids are strings. A candidate's `source` is the **source type** (`"jira"`,
> `"confluence"`, `"upload"`, `"notion"`, …) — handy for icons.

```ts
// ───────────────────────── LIST ─────────────────────────
interface RagTraceListResponse {
  traces: RagTraceListItem[];
  count: number;   // number of rows in THIS page (not a grand total — see notes)
  limit: number;
  offset: number;
}

interface RagTraceListItem {
  trace_id: string;            // uuid
  created_at: string | null;   // ISO8601
  query: string;               // = input.raw_user_message
  source: string | null;       // "oai_compat" | "rest" | ...
  total_ms: number;
}

// ─────────────────────── DETAIL (GET /{id}) ───────────────────────
interface RagTrace {
  trace_id: string;                 // uuid, matches the answer footer
  source: string | null;            // surface: "oai_compat" | "rest"
  workspace_id: string | null;
  user_id: string | null;
  agent_id: string | null;          // null for chat/OAI; populated for MCP agents later
  input: TraceInput;
  phases: Phase[];                  // always in order (see union below)
  total_ms: number;                 // full pipeline time, ms
  created_at: string | null;        // ISO8601 — merged in from the row
}

interface TraceInput {
  raw_user_message: string;         // the user's original message
  history: string[];                // ⚠️ currently always [] (context is folded into composite_query)
  composite_query: string | null;   // history-aware query — what actually entered the pipeline
}

// ───────────────────────── PHASES ─────────────────────────
// Discriminator is the `name` field. Array order:
// resolve_query → query_expansion → translate_query → classify →
// recall → merge_and_score → rerank → context_assembly → generation
type Phase =
  | LlmStepPhase       // resolve_query | query_expansion | translate_query
  | ClassifyPhase
  | RecallPhase
  | MergePhase
  | RerankPhase
  | ContextPhase
  | GenerationPhase;

// Preprocessing steps (LLM calls); input/output are strings
interface LlmStepPhase {
  name: "resolve_query" | "query_expansion" | "translate_query";
  type: "llm";
  input: string;
  output: string;
}

interface ClassifyPhase {
  name: "classify";
  type: "llm";
  output: {
    profile: string;       // "execution" | "documentation" | "user_file" | "relationship" | "temporal" | "mixed"
    method: string;        // "rule" | "llm" | "disabled"
    confidence: number;    // 0..1
  };
}

// Candidate from a recall channel (carries raw_score)
interface RecallCandidate {
  chunk_id: string;
  doc_label: string;
  title: string;
  source: string;          // source type for the icon (jira/confluence/...)
  text: string;            // FULL chunk text (can be large)
  raw_score: number;       // raw channel score
}

interface RecallChannel {
  count: number;
  candidates: RecallCandidate[];
}

interface RecallPhase {
  name: "recall";
  channels: {
    dense: RecallChannel;
    exact: RecallChannel;
    metadata: RecallChannel;
    graph: RecallChannel;
  };
}

// Candidate after merge + scoring (no raw_score, but with a per-signal breakdown)
interface MergeCandidate {
  chunk_id: string;
  doc_label: string;
  title: string;
  source: string;
  text: string;
  found_by: string[];                       // which channels found it, e.g. ["dense","graph"]
  channel_scores: Record<string, number>;   // raw per-channel scores, e.g. {"dense":0.02}
  recency: number | null;                   // recency signal
  balance: number | null;                   // source-balance signal
  signal_score: number;                     // final weighted signal score
}

interface MergePhase {
  name: "merge_and_score";
  weights: Record<string, number>;          // profile weights: dense_weight, graph_weight, metadata_weight, recency_weight, balance_weight (+ freshness_weight if active)
  candidates: MergeCandidate[];             // the WHOLE pool before the confidence filter
  dropped_by_min_signal: string[];          // chunk_ids dropped by MIN_SIGNAL_SCORE (default [] — filter off)
}

// Candidate after the reranker
interface RerankCandidate {
  chunk_id: string;
  doc_label: string;
  title: string;
  source: string;
  text: string;
  rerank_score: number;     // cross-encoder score (normalized)
  final_score: number;      // blended signal+rerank — the output ordering
  kept: boolean;            // in the final set (currently always true: the phase holds only the kept top-k, captured AFTER the ACL post-filter)
}

interface RerankPhase {
  name: "rerank";
  enabled: boolean;         // whether the reranker ran (RERANKER_ENABLED)
  pool_size: number;        // size of the pool sent to the reranker
  candidates: RerankCandidate[];
}

interface Fragment {
  doc_label: string;
  title: string;
  text: string;
}

interface ContextPhase {
  name: "context_assembly";
  primary_fragments: Fragment[];      // PRIMARY evidence
  supporting_fragments: Fragment[];   // SUPPORTING evidence
  graph: {
    entities: GraphItem[];            // graph entities (name/type/aliases, ...)
    relations: GraphItem[];           // relations (source/target/type)
    docs: GraphItem[];                // doc labels/nodes from the graph
  };
  assembled_prompt: string;           // the FULL context actually sent to the LLM (user part of the prompt)
}

// Graph items are objects of arbitrary shape (depends on graph data).
// Typed loosely; common fields are optional.
interface GraphItem {
  name?: string;
  type?: string;
  source?: string;
  target?: string;
  [k: string]: unknown;
}

// Generation: either success or error
type GenerationPhase = GenerationOk | GenerationError;

interface GenerationOk {
  name: "generation";
  provider: string;        // "deepseek" | "ollama" | "openrouter" | "custom"
  model: string;           // e.g. "deepseek-chat"
  raw_answer: string;      // model output BEFORE the sources block is appended
  final_answer: string;    // final answer WITH sources (without the trace footer)
}

interface GenerationError {
  name: "generation";
  error: string;           // e.g. "llm_answer_failed"
  raw_answer: null;
  // provider/model/final_answer are absent in this branch
}
```

---

## Notes (important for the UI)

- **`raw_score` exists only on `RecallCandidate`.** In merge it's `channel_scores` + `signal_score`,
  in rerank it's `rerank_score` / `final_score`. Don't look for the same field across all phases.
- **`text` is stored in full** in every candidate (recall/merge/rerank) and in fragments — strings can
  be large (tens of KB combined). Collapse / lazy-expand them on the page.
- **A candidate's `source` is the source type** (jira/confluence/upload/notion). Icon mapping is the
  same as the main UI: 📄 confluence, 📋 jira, 📎 upload, 📓 notion.
- **`agent_id` is currently `null`** for chat/OAI (will be populated once tracing is wired into MCP agents).
- **`history` is currently always `[]`** — history is folded into `composite_query`.
- **`count` in the list response is the page size**, not a grand total; paginate via `limit`/`offset`
  and stop when fewer than `limit` rows come back.
- **Phase order is fixed**, but a phase can collapse (e.g. `recall.channels.exact.count = 0`). Render by
  the data actually present, not by index.
- **The `GenerationError` branch** appears when the LLM call failed — the phase carries `error` and no
  `final_answer`. The trace is still persisted (partial — up to the point of failure).
