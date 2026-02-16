# Metatron Core (MTRNIX)

Open-source enterprise knowledge management system. Ingest documents from Confluence, Jira, and other sources. Ask questions via Telegram or Discord bot — get answers grounded in your organization's real data.

## Features
- **Hybrid RAG**: Dense vectors + BM25 + knowledge graph enrichment
- **Connectors**: Confluence, Jira (Notion, GitHub, Google Drive planned)
- **Smart Search**: Query expansion, date filtering, source diversity, person detection
- **Telegram Bot**: Ask questions, sync data, check status — all from Telegram
- **Discord Bot**: Same features available via Discord DMs
- **Slack Bot**: Same features available via Slack DMs
- **On-premise**: Self-hosted, your data never leaves your infrastructure
- **Multi-language**: Russian and English queries and documents

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Python 3.12+
- Telegram bot token (from @BotFather) and/or Discord bot token (from Developer Portal) and/or Slack tokens (from Slack API)

### 1. Clone and configure
```bash
git clone <repo-url>
cd metatron-core
cp .env.example .env
# Edit .env — add your tokens and credentials
```

### 2. Start infrastructure
```bash
docker compose up -d
# Starts: Qdrant, Memgraph, PostgreSQL, Ollama
```

### 3. Install Python dependencies
```bash
pip install -e ".[dev,channels]"
```

### 4. Start the application
```bash
python -m metatron.app
```
This starts the API server and any configured bots (Telegram, Discord, Slack) in a single process.
Each bot starts only if its token is set in `.env`.

### 5. Sync data sources (in Telegram, Discord or Slack)
```
/sync confluence
/sync jira
```

Then ask any question — the bot searches your knowledge base.

### 6. Run tests
```bash
pytest tests/unit/
# Expected: 295+ tests passing
```

## Configuration

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes (for Telegram) | Token from @BotFather |
| `DISCORD_BOT_TOKEN` | Yes (for Discord) | Token from Discord Developer Portal |
| `SLACK_BOT_TOKEN` | Yes (for Slack) | xoxb-... from OAuth & Permissions |
| `SLACK_APP_TOKEN` | Yes (for Slack) | xapp-... from Socket Mode settings |

See `.env.example` for all configuration variables.

## Bot Commands (Telegram, Discord & Slack)
- `/start` — Greeting and capabilities
- `/search <query>` — Explicit search
- `/sync confluence|jira` — Sync data source
- `/status` — Workspace stats
- `/clear` — Clear conversation history
- `/help` — List commands

## Architecture
See `CLAUDE.md` for detailed architecture and `docs/TODO.md` for roadmap.

## License
Apache 2.0
