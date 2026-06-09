# Context Glossary — Metatron Core

A shared glossary of domain terms. Definitions only — no implementation details.
Update inline as terms are resolved during design discussions.

## Terms

### Proxy path
The new `POST /v1/proxy/chat/completions` surface (MTRNIX-372). Metatron sits between a
customer agent and that agent's real upstream LLM, enriches the request with context, and
streams the upstream response back verbatim. Requires an explicit agent identity on the wire.

### Legacy RAG path
The pre-existing `POST /v1/chat/completions` surface. Answers a query by running Metatron's
own retrieval + LLM synthesis over a workspace's knowledge base (it does **not** forward to a
per-agent upstream LLM). As of MTRNIX-372 it is refactored into a thin handler over the shared
Dispatch entrypoint running in `rag` mode — the RAG answer behaviour (and its SSE/citation
output) is preserved bit-for-bit, guarded by a golden-file regression test. Turning this path
into a real upstream forward is the deferred cutover, not part of this work.

### Dispatch entrypoint / mode
The single orchestration entrypoint both routes delegate to. Mode is route-derived, never
stored: `rag` (legacy path — Metatron answers via its own retrieval+LLM) vs `proxy` (new path
— forward enriched request to the agent's upstream LLM). Shared across modes: agent
resolution, correlation id, and the `proxy.*` activity events. The enrichment block assembler
is only exercised in `proxy` mode.

### System chat agent
A registry agent auto-created one-per-workspace, flagged so it is hidden from the default
agent list. It exists so that a Legacy RAG call arriving without an explicit agent identity
still resolves to a real registry agent (one mental model of "agent"), rather than being a
special identity-less case.

### Upstream LLM
The customer agent's own real LLM provider (OpenAI, OpenRouter, vLLM, Ollama, etc.) that the
Proxy path forwards an enriched request to. Distinct from Metatron's internal LLM used by the
Legacy RAG path for synthesis.

### Enrichment / Enrichment block
The structured context Metatron appends to the incoming system message on the Proxy path:
`<constitution>` / `<preferences>` / `<relevant_memories>` / `<relevant_knowledge>` sections.
The customer agent's own system prompt is never rewritten — only appended to.

### Tool-result round
An inbound proxy request whose tail message is a tool result (not a new user message). On
these rounds the enrichment is additive: matched-entity memories are appended to the existing
`<relevant_memories>` section rather than the whole block being rebuilt.

### Agent (registry agent)
A record in the agent registry with an identity, capabilities, and a per-agent upstream LLM
configuration. The Proxy path requires the caller to name one explicitly.

### Manual sync
A sync of a connection's source triggered on demand by an explicit user action (the
`POST /connections/{id}/sync` call). One-shot; carries no schedule.

### Autosync
Schedule-driven syncing of a connection: the system fires syncs of a connection's source on
a recurring schedule with no per-run user action. Opposed to **Manual sync**. A connection
with no schedule is not autosynced.

### Sync schedule
The recurring time specification attached to a connection that drives **Autosync** — a cron
expression. Absent schedule = autosync off. Cron is interpreted in the deployment's single
configured timezone (default UTC), not per-connection.

### Scheduled sync
A single sync run whose origin is **Autosync** (the schedule fired it) rather than a user
action. Distinct from **Manual sync** only in origin; the underlying sync work is identical.
