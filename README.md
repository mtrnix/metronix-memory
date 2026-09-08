# Metronix Memory

<p align="center">
  <img src="docs/metronix-banner.svg" alt="Metronix Memory" width="600">
</p>

**Self-hosted memory infra for AI agents — MCP-native, local-model friendly: hybrid RAG + temporal knowledge graph, durable memory, freshness checks, and agent-scoped context.**

Metronix is a backend agents can call: ingest files and SaaS knowledge, retrieve with dense + sparse + graph context, store durable facts and preferences per agent, and keep long-lived knowledge fresh as projects change.

<p align="center">
  <img alt="License: Apache-2.0" src="https://img.shields.io/badge/License-Apache--2.0-blue.svg">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-native-111111">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12--3.13-3776AB?logo=python&logoColor=white">
</p>

## What you get

- **Durable memory for every agent** — facts, preferences, and pinned context with workspace and agent scoping
- **Hybrid knowledge retrieval** — dense + SPLADE sparse + Neo4j graph context, with source citations
- **Self-hosted control** — Docker Compose stack, bundled local models, optional external answer generation
- **One integration surface** — MCP today; REST and OpenAI-compatible APIs when you need them

## Quick start

Requirements: Docker with **≥6 GB RAM** (8 GB recommended) and ~15 GB free disk.

```bash
# One-liner (latest tagged release)
curl -fsSL https://mtrnix.com/install.sh | bash

# Or clone and install
git clone https://github.com/mtrnix/metronix-memory.git
cd metronix-memory
./install.sh                              # agent memory (default)
# ./install.sh --mode answers --openwebui -y   # optional chat UI + answers
curl http://localhost:8000/health
# {"status":"ok"}
```

Then connect an agent: **[Connecting to an agent](connecting_to_agent.md)**.

Full install (prerequisites, `.env`, ports, troubleshooting): **[install.md](install.md)**.

<p align="center">
  <img src="docs/metronix-agent-memory-demo.gif" alt="Metronix demo: an agent remembering across sessions" width="720">
</p>

## Why Metronix

| Option | What it gives you | What Metronix adds |
| --- | --- | --- |
| Vector DB | Similarity search | Ingestion, MCP tools, durable agent memory, sparse + graph retrieval |
| Long context | More tokens in one prompt | Persistent memory across sessions, scoping, freshness |
| Chat history | Transcript recall | Structured facts/preferences, temporal knowledge, reusable MCP context |
| RAG framework | Building blocks | Operational backend: connectors, APIs, MCP, memory lifecycle |

## Benchmarks

Directional N=1 results under `benchmark-protocol v1.0` (same answer model, same blind judge, retrieval + end-to-end layers):

| Benchmark | Scope | Layer B | Retrieval / signal |
| --- | --- | --- | --- |
| LoCoMo | 1,982 QA pairs | **52.8%** | Recall@10 **85.3%** |
| LongMemEval-S | 500 questions | **59.0%** | Recall@10 **95.4%** · [harness](benchmarks/longmemeval) |
| MemoryAgentBench | 2,800 tasks | **63.6%** | Accurate Retrieval **84.7%** · EventQA blended **86.8%** |
| EventQA | MAB 65K + 131K | **86.8%** blended | 98.0% @ 65K · 94.8% @ 131K |
| BEAM 100K | 400 questions | **32.1%** | Recall@10 2.9% · Layer B is the meaningful figure |

Pattern: retrieval usually finds the evidence; answer synthesis and preference following remain the hard part. Details: [docs/benchmarks/longmemeval.md](docs/benchmarks/longmemeval.md).

## Connect an agent

| Runtime | Guide |
| --- | --- |
| Any MCP client | [Connecting to an agent](connecting_to_agent.md) · [prompts.md](prompts.md) |
| Hermes | [Native provider](https://github.com/mtrnix/hermes-memory-metronix) · [MCP guide](docs/integrations/hermes-agent.md) |
| Cursor | [Cursor](docs/integrations/cursor.md) |
| Claude Desktop / Code | [Desktop](docs/integrations/claude-desktop.md) · [Code](docs/integrations/claude-code.md) |
| OpenCode · Codex · OpenClaw | [OpenCode](docs/integrations/opencode.md) · [Codex](docs/integrations/codex.md) · [OpenClaw](docs/integrations/openclaw.md) |
| LangChain · LangGraph · LlamaIndex | [LangChain](docs/integrations/langchain.md) · [LangGraph](docs/integrations/langgraph.md) · [LlamaIndex](docs/integrations/llamaindex.md) |
| SDKs · n8n | [Python](docs/integrations/sdk-python.md) · [Go](docs/integrations/sdk-go.md) · [n8n](docs/integrations/n8n.md) |

Full index: [docs/README.md](docs/README.md).

## Architecture

One-way layers — each level only imports downward:

```text
L6  api/            REST + OpenAI-compatible API + MCP HTTP mount
L5  channels/       Legacy Telegram, Discord, Slack integrations
L4  agent/          Intent router and compatibility shims
L3  services/       Connectors, LLM, MCP, memory, auth, workspaces, knowledge
L2  processing/     Ingestion, retrieval, freshness pipeline
L1  storage/        PostgreSQL, Qdrant, Neo4j, Redis clients
L0  core/           Config, models, events, plugin interfaces
```

| Pipeline | What it does |
| --- | --- |
| **Ingestion** | Fetch → parse → chunk → embed → store (connectors + files) |
| **Retrieval** | Classify → expand → recall → rerank → score → answer (dense + sparse + graph) |
| **Freshness** | Detect stale or conflicting memory and knowledge |
| **Memory** | Store → search → review → assemble (workspace / agent scoped) |

Interactive diagram (offline): [docs/architecture-diagram.html](docs/architecture-diagram.html).

## Admin console (optional)

Open-source web UI for connectors, uploads, channels, and health — presentation-only over the REST API:

```bash
docker compose --profile admin up -d --build   # → https://localhost:3000
```

Details: [frontend/README.md](frontend/README.md). The broader Control Center product is separate and not in this repo.

## Documentation

| Doc | Purpose |
| --- | --- |
| [install.md](install.md) | Full install, ports, troubleshooting |
| [connecting_to_agent.md](connecting_to_agent.md) | MCP setup for any agent |
| [prompts.md](prompts.md) | Paste-ready agent setup prompts |
| [docs/MCP_API.md](docs/MCP_API.md) | MCP tool reference |
| [docs/API.md](docs/API.md) | REST API reference |
| [docs/README.md](docs/README.md) | Documentation index |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

## Development

```bash
make dev              # uvicorn --reload
make test             # pytest unit tests
make lint             # ruff check + format check
make typecheck        # mypy src/metronix/
make migrate          # alembic upgrade head
```

## FAQ

**Is Metronix hosted?**  
No — it is self-hosted. You run the backend and choose where data lives.

**Can multiple agents share one backend without leaking memory?**  
Yes. Memory is scoped by workspace and `agent_id`. Share a workspace for org knowledge; keep private memory per agent.

**Is this for Raspberry Pi or zero-latency voice loops?**  
No. Metronix is a server-side backend. Run it on a machine with enough RAM, and have edge clients connect over REST/MCP.

**Native Hermes provider vs MCP?**  
Use the [native provider](https://github.com/mtrnix/hermes-memory-metronix) for automatic prefetch/write-through; use MCP for explicit knowledge-base tools. They complement each other — see [Hermes MCP guide](docs/integrations/hermes-agent.md).

**How does MCP authentication work?**  
Local/self-hosted defaults use `AUTH_ENABLED=false` with `METRONIX_MCP_API_KEY`. Hosted deployments with `AUTH_ENABLED=true` require a user JWT instead — see [install.md](install.md) and [connecting_to_agent.md](connecting_to_agent.md).

**How do I verify memory actually works?**  
Store a distinctive record, then search via REST or `metronix_memory_search`. Do not rely only on asking an LLM “do you remember X?” — see [install.md](install.md) verify steps and [connecting_to_agent.md](connecting_to_agent.md).

## Contributing & support

Bug reports and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).  
Issues: [github.com/mtrnix/metronix-memory/issues](https://github.com/mtrnix/metronix-memory/issues).

## License

Apache License 2.0. See [LICENSE](LICENSE).

**⭐ Star us if you build agents with memory.**
