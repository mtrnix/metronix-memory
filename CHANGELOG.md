# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- "Quick Validation" section in `README.md` documenting the store→retrieve memory
  lifecycle over both the REST API and the MCP interface (thanks @gsrtech100-wq, idea
  from #263).

### Changed

- Renamed the canonical Compose file `docker-compose.full.yml` → `docker-compose.yml` so
  `docker compose up` starts the core stack with no `-f` flag. Optional UI services (KB
  Admin Console, Open WebUI) remain opt-in behind Compose profiles; all docs and
  `install.sh` updated accordingly. Internal container, volume, and network names are
  unchanged, so existing deployments keep their data.

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
