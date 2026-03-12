# Observability

## Overview
Cross-cutting — not in the L0-L6 dependency hierarchy. Health checks, metrics collection,
and request timing. Used by storage layer (health checks), retrieval (timing), and API (metrics endpoint).

## Files

### `health.py`
`HealthChecker` — async health checks for all external dependencies.
`check_all() -> dict[str, str]` — runs all checks, returns `{service: status}`.

Individual checks (currently all stub `"unchecked"`):
- `check_postgres()` — PostgreSQL connectivity
- `check_qdrant()` — Qdrant vector store
- `check_memgraph()` — Memgraph graph DB
- `check_ollama()` — Ollama LLM

Used by `GET /ready` endpoint in `api/routes/health.py` (which has its own
inline sync check helpers for the actual connectivity tests).

### `metrics.py`
`MetricsCollector` — thread-safe operation counters.
- `record_success(module, operation)` — increments success counter
- `record_error(module, operation, error_type)` — increments error counter
- `get_metrics() -> dict` — returns current counts snapshot
- `reset_metrics()` — clears all counters

Module-level singleton via `get_metrics_collector()`. `reset_metrics()` used by
`POST /api/v1/metrics/reset`.

`@timed(step_name)` decorator — measures function wall time, records in `QueryTrace`.
`Timer` context manager — same timing, used inline in pipeline steps.

### `tracer.py`
`QueryTrace` — per-request step timing for the 7-step retrieval pipeline.
Uses `QueryStep` from `core.models`.

`start_step(name)` / `end_step(name)` — record duration for named step.
Steps: `embed_query`, `dense_search`, `sparse_search`, `rrf_fusion`,
`graph_enrichment`, `multi_factor_scoring`, `context_assembly`.

`to_dict() -> dict` — serialized trace for benchmarker API response.

## Key Patterns
- **Thread-safe metrics** — `threading.Lock` guards all counter mutations
- **Module-level singleton** — `get_metrics_collector()` returns the same instance everywhere
- **`@timed` decorator** — applied to `hybrid_search_and_answer()` and individual pipeline steps

## Dependencies
- **Depends on**: `core.models` (QueryStep)
- **Depended on by**: `api.routes.health` (health checks), `api.routes.benchmarker` (QueryTrace), `retrieval.search` (@timed decorator)
