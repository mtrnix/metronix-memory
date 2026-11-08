# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [v2026.11.08] - 2026-11-08

### Added

- **One-command install**: `scripts/quickstart.sh` (or
  `curl -fsSL https://mtrnix.com/install.sh | bash -s -- -- --quickstart`) goes from a clean
  machine to a verified agent memory with no prompts: one `.env` with every generated
  secret, stack up, `/ready` wait with per-service and model-pull progress, a personal
  per-agent `mtk_` key, ready-to-paste MCP configs for Claude Desktop, Cursor and VS Code,
  an end-to-end smoke test, and the final credentials. Exits non-zero at the first failure.
- `scripts/provision_agent.sh` issues (or reuses) the per-agent key, stored as
  `METRONIX_AGENT_KEY`; `scripts/smoke_e2e.sh` stores a fact, restarts `metronix-core`
  and recalls it.
- `install.sh --quickstart`, `--no-connect`, `--with-graph-model`; bootstrap `--quickstart`.
- CI job `quickstart-e2e` runs the quickstart and smoke test from a clean runner on every PR.

### Changed

- `/health` returns 503 when the startup migration failed (#539). `/ready` also checks that
  the schema is at the Alembic head and returns 503 (not 200) when any check is degraded,
  including a missing embedding model (#541).
- The graph-extraction model (`qwen2.5:3b`, ~2 GB) is no longer pulled at install; the API
  pulls it on first use, or at start with `--with-graph-model` / `OLLAMA_PULL_LLM_MODEL=true`.
- `install.sh` generates `AUTH_PASSWORD` (seeds `admin@metronix.local`) with the other
  secrets and wires agents with `METRONIX_AGENT_KEY` when present instead of the shared
  `METRONIX_MCP_API_KEY`, which memory tools reject (#540). Docs updated accordingly.

### Fixed

- Image builds survive slow networks: pip timeout 120 s with 10 retries.
- SPLADE healthcheck no longer imports `httpx` (not a SPLADE dependency), which kept
  SPLADE unhealthy and `metronix-core` from starting on fresh builds.
- `install.sh` no longer blames a Neo4j password mismatch for every compose failure.

This release also contains everything merged to `main` since `v2026.08.19.1`
(`git log v2026.08.19.1..v2026.11.08`).

## [v2026.07.08] - 2026-07-08

### Added

- "Quick Validation" section in `README.md` documenting the store→retrieve memory
  lifecycle over both the REST API and the MCP interface (thanks @gsrtech100-wq, idea
  from #263).

### Changed

- Replaced nginx with **Caddy** in the `frontend` container and switched the web UI to
  **HTTPS**. The console is now served over `https://localhost:3000` using Caddy's
  internal CA (self-signed) by default; set `CADDY_DOMAIN` to a public domain and drop
  `tls internal` in `frontend/Caddyfile` for automatic Let's Encrypt. SPA fallback,
  `/api`·`/health`·`/ready`·`/metrics` proxying to `metronix-core:8000`, the FastAPI
  307 trailing-slash rewrite (excluding `/upload`), and gzip/zstd compression are all
  preserved. Closes #320.
- Renamed the optional web UI from "KB Admin Console" / `--profile kb` to
  **"Metronix Admin Console" / `--profile admin`** (it is the admin panel for the
  memory backend, not a knowledge-base-specific tool). `install.sh` now uses `--admin`
  (`--kb` is kept as a deprecated alias printing a warning); `KB_FRONTEND_PORT` is
  renamed to `ADMIN_FRONTEND_PORT` (legacy value still honored as a fallback for one
  release). In-app branding updated from "Metronix KB" to "Metronix Admin".
  The `origin: "agent" | "kb" | "all"` API data-origin enum is **unchanged** (it refers
  to knowledge-base content, not the panel).
- Renamed the canonical Compose file `docker-compose.full.yml` → `docker-compose.yml` so
  `docker compose up` starts the core stack with no `-f` flag. Optional UI services (now
  the Metronix Admin Console, Open WebUI) remain opt-in behind Compose profiles; all docs
  and `install.sh` updated accordingly. Internal container, volume, and network names are
  unchanged, so existing deployments keep their data.

### Removed

- `frontend/nginx-kb.conf` (replaced by `frontend/Caddyfile`).

## [1.0.0] - 2026-06-29

### Added

- Hybrid RAG combining vector search (Qdrant), keyword search, and graph traversal (Neo4j)
- Durable agent memory with workspace and agent-level scoping
- MCP server at `/mcp` with tools for memory storage, retrieval, and status
- REST API at `/api/v1` and OpenAI-compatible chat API at `/v1`
- Local embedding and LLM support via Ollama
- Knowledge ingestion pipeline from files and connectors
- Docker Compose deployment stack (FastAPI, PostgreSQL, Qdrant, Neo4j, Redis, Ollama, SPLADE)
- Integration guides for 20+ agent runtimes and clients
- Deployment checklist (`docs/deployment.md`) for self-hosted production use

### Changed

- Prepared the repository for open-source publication.
- Restructured installation documentation: a single full-install guide (`install.md`) on
  the `docker-compose.yml` stack, with a minimal quickstart in `README.md`.
- Reworked agent setup into `connecting_to_agent.md` (prompt-based and manual paths), with
  all setup prompts collected in `prompts.md`.
- Added public MCP agent setup instructions in `connecting_to_agent.md`.

### Removed

- Internal development artifacts, demo seed data, private deployment workflows, and stale planning documentation from the public tree

[Unreleased]: https://github.com/mtrnix/metronix-memory/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/mtrnix/metronix-memory/releases/tag/v1.0.0
