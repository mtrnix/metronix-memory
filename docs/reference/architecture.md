# Architecture Reference

Metronix Memory is organized as strict one-way layers:

```text
L6 api/            REST, OpenAI-compatible, MCP HTTP mount
L5 channels/       Legacy channel integrations
L4 agent/          Intent routing and compatibility shims
L3 services        Connectors, LLM, MCP, memory, auth, workspaces, knowledge
L2 processing      Ingestion, retrieval, freshness pipeline
L1 storage/        PostgreSQL, Qdrant, Neo4j, Redis clients
L0 core/           Config, models, events, plugin interfaces
```

Lower layers must not import upward. Core has no dependencies on storage, API, or service
packages.

See the interactive diagram at `../architecture-diagram.html`.
