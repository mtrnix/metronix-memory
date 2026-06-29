# Open-Core Boundaries

Metronix Memory is the open-source runtime for self-hosted AI memory and hybrid RAG.
It is designed to run on your infrastructure and expose the same capabilities through
MCP, OpenAI-compatible, and REST APIs.

## What Is In Core

Core includes the backend services required to ingest, index, search, and manage memory:

- PostgreSQL, Qdrant, Neo4j, and Redis as the storage stack.
- SPLADE sparse retrieval and dense embedding support.
- The Metronix Memory API, including REST, OpenAI-compatible, and MCP surfaces.
- Document ingestion, connector sync, search, graph enrichment, and reranking.
- Agent memory, memory review APIs, snapshots, and freshness worker support.
- Open WebUI integration for chat with memory through the OpenAI-compatible API.

## Optional UI

The knowledge-base UI is a separate frontend that can be run next to Core when available.
Core does not require it: every backend capability is available through API and MCP surfaces.

## Outside This Repository

Commercial administration features are intentionally outside this repository. That includes
advanced company administration, SSO, expanded governance, commercial dashboards, and other
Control Center features.

The public Core repository should not require those components for installation, local
development, or agent integration.
