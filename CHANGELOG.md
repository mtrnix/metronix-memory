# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [1.0.0] - 2026-06-29

### Added

- Hybrid RAG combining vector search (Qdrant), keyword search, and graph traversal (Neo4j)
- Durable agent memory with workspace and agent-level scoping
- MCP server at `/mcp` with tools for memory storage, retrieval, and status
- REST API at `/api/v1` and OpenAI-compatible chat API at `/v1`
- Local embedding and LLM support via Ollama
- Knowledge ingestion pipeline from files and connectors
- Docker Compose deployment stack (FastAPI, PostgreSQL, Qdrant, Neo4j, Redis, Ollama, SPLADE)
- Integration guides for 15+ agent runtimes and clients
- Deployment checklist (`docs/deployment.md`) for self-hosted production use

### Changed

- Prepared the repository for open-source publication
- Consolidated installation documentation around `manual.md`, `install.md`, and `docker-compose.full.yml`
- Added public MCP agent setup instructions in `connecting_to_agent.md`

### Removed

- Internal development artifacts, demo seed data, private deployment workflows, and stale planning documentation from the public tree

[Unreleased]: https://github.com/mtrnix/metronix-memory/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/mtrnix/metronix-memory/releases/tag/v1.0.0
