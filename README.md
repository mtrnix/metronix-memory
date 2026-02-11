# Metatron Core

Open-source AI knowledge agent for teams. Connects to corporate tools (Confluence, Jira, Notion, GitHub, Google Drive, Slack), indexes documents into vector + graph databases, and answers questions via messenger bots.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         CHANNELS                                 │
│                  Telegram Bot | Slack Bot                        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT / ROUTER                              │
│              (OpenClaw LLM-based routing)                        │
└────────────┬────────────────────────────────────────────────────┘
             │
             ├─────────────┬──────────────┐
             ▼             ▼              ▼
      ┌──────────┐  ┌──────────┐  ┌──────────┐
      │  Skills  │  │Retrieval │  │   LLM    │
      │ (from DB)│  │ Pipeline │  │ (Ollama) │
      └──────────┘  └────┬─────┘  └──────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                         STORAGE                                  │
│     Qdrant (vectors) | Memgraph (graph) | PostgreSQL (data)     │
└────────────┬────────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────────┐
│                       CONNECTORS                                 │
│  Confluence | Jira | Notion | GitHub | Google Drive | Slack     │
└─────────────────────────────────────────────────────────────────┘
```

## Features

- **Multi-source ingestion**: Connects to Confluence, Jira, Notion, GitHub, Google Drive, Slack
- **Hybrid search**: Dense + sparse retrieval with Reciprocal Rank Fusion (RRF)
- **Knowledge graph enrichment**: Entities and relationships stored in Memgraph
- **Root-child chunking**: OpenMemory-inspired hierarchical chunking strategy
- **SimHash deduplication**: Content-based dedup across sources
- **Multi-factor scoring**: 6 signals for relevance ranking (semantic, lexical, recency, authority, graph, user context)
- **LLM-as-Router**: OpenClaw-inspired routing between skills
- **Skill system**: Skills stored as Markdown in database, not files
- **Graceful degradation**: `_safe_call` wrappers for fault tolerance
- **Per-workspace isolation**: Multi-tenant data separation
- **Full query tracing**: 7-step observability for every query
- **JWT authentication**: RBAC with role-based access control

## Quick Start

### Prerequisites

- Python 3.12+
- Docker and Docker Compose
- Make (optional, but recommended)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/metatron-core.git
cd metatron-core

# Copy environment variables
cp .env.example .env

# Setup Python environment
make setup

# Start infrastructure services
docker compose up -d

# Run database migrations
make migrate

# Start development server
make dev
```

The API will be available at `http://localhost:8000`. API documentation is at `http://localhost:8000/docs`.

## Tech Stack

- **Language**: Python 3.12
- **Web Framework**: FastAPI
- **Vector Database**: Qdrant
- **Graph Database**: Memgraph
- **Relational Database**: PostgreSQL
- **LLM Integration**: Ollama (local), OpenAI/Anthropic (cloud)
- **Embeddings**: sentence-transformers, OpenAI
- **Task Queue**: Celery + Redis
- **Message Channels**: python-telegram-bot, slack-sdk
- **Testing**: pytest, pytest-asyncio
- **Linting**: ruff, mypy
- **Packaging**: Poetry

## Project Structure

```
src/metatron/
├── core/              # L0: Base utilities, config, interfaces
├── storage/           # L1: Database clients (Qdrant, Memgraph, PostgreSQL)
├── ingestion/         # L2: Document processing, chunking, embedding
├── retrieval/         # L2: Hybrid search, reranking, scoring
├── connectors/        # L3: External integrations (Confluence, Jira, etc.)
├── skills/            # L3: Skill definitions and execution
├── llm/               # L3: LLM providers and prompting
├── auth/              # L3: Authentication and authorization
├── agent/             # L4: Router logic and orchestration
├── channels/          # L5: Telegram, Slack bots
└── api/               # L6: REST API endpoints
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed design documentation.

## Configuration

Configuration is managed through environment variables. Key settings:

- `DATABASE_URL`: PostgreSQL connection string
- `QDRANT_URL`: Qdrant vector database URL
- `MEMGRAPH_HOST`: Memgraph host and port
- `OLLAMA_BASE_URL`: Ollama API endpoint
- `OPENAI_API_KEY`: OpenAI API key (optional)
- `TELEGRAM_BOT_TOKEN`: Telegram bot token
- `SLACK_BOT_TOKEN`: Slack bot token
- `JWT_SECRET_KEY`: Secret for JWT signing

See `.env.example` for full configuration options.

## Development

```bash
# Install dependencies
make setup

# Run tests
make test

# Run linting
make lint

# Run type checking
make typecheck

# Format code
make format

# Run all checks (lint + typecheck + test)
make check
```

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for production deployment guidelines.

## Contributing

Contributions are welcome! Please read [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for guidelines on:

- Code style and conventions
- Testing requirements
- Pull request process
- Development workflow

## License

Apache 2.0

## Support

- Documentation: [docs/](docs/)
- Issues: GitHub Issues
- Discussions: GitHub Discussions
