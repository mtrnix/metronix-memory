# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Default `docker-compose.yml` file at the root of the repository for a minimal Docker Quick Start (core services only).
- "Quick Validation" section to the `README.md` to document verification of the API using HTTP endpoints.

### Changed

- Standardized default API port from 8001 to 8000.
- Migrated legacy Python installation flows into a robust cross-platform shell installer `install.sh`.
- Hardened default Neo4j authentication setup in compose files to prevent blank-password initialization issues.

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
  the `docker-compose.full.yml` stack, with a minimal quickstart in `README.md`.
- Reworked agent setup into `connecting_to_agent.md` (prompt-based and manual paths), with
  all setup prompts collected in `prompts.md`.
- Added public MCP agent setup instructions in `connecting_to_agent.md`.

### Removed

- Internal development artifacts, demo seed data, private deployment workflows, and stale planning documentation from the public tree

[Unreleased]: https://github.com/mtrnix/metronix-memory/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/mtrnix/metronix-memory/releases/tag/v1.0.0
