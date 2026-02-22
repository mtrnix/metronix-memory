# Metatron Installation Guide

Welcome! This guide walks you through installing Metatron Core (MTRNIX) on your system.

## Quick Start

The simplest way to install Metatron is with a single command:

```bash
curl https://app.mtrnix.com/install.sh | bash
```

This automatically checks your system for dependencies, clones the repository, and starts the Docker Compose stack.

## Prerequisites

Before running the installer, ensure you have:

- **Python 3.12+** — Required for running the Metatron application
  - Check your version: `python3 --version`
  - [Install Python](https://www.python.org/downloads/)
  
- **Docker** — Required for containerized services (PostgreSQL, Qdrant, Memgraph, Ollama)
  - Check if installed: `docker --version`
  - [Install Docker](https://docs.docker.com/get-docker/)
  
- **Docker Compose** — For orchestrating multiple containers
  - Check if installed: `docker-compose --version` or `docker compose version`
  - Usually installed with Docker Desktop; [learn more](https://docs.docker.com/compose/install/)
  
- **Git** — For cloning the repository
  - Check if installed: `git --version`
  - [Install Git](https://git-scm.com/download/)

## Security: Verify Checksum Before Running

**Important:** Always verify the installer's integrity before piping it to bash. This prevents tampering or accidental corruption.

### 1. Download the checksum file

```bash
curl -fsSL https://raw.githubusercontent.com/openclaw/metatron/main/.sha256sum -o install.sha256
```

### 2. Download the installer

```bash
curl -fsSL https://app.mtrnix.com/install.sh -o install.sh
```

### 3. Verify the checksum matches

```bash
sha256sum -c install.sha256
```

Expected output:
```
install.sh: OK
```

### 4. Run the verified installer

```bash
bash install.sh
```

## Manual Installation (Without curl | bash)

If you prefer not to pipe scripts to bash, you can install manually:

### 1. Clone the repository

```bash
git clone https://github.com/openclaw/metatron.git
cd metatron
```

### 2. Copy configuration template

```bash
cp .env.example .env
# Edit .env to add your API tokens (Telegram, Discord, Slack)
```

### 3. Start the Docker Compose stack

```bash
docker-compose up -d
# or: docker compose up -d
```

This starts:
- **PostgreSQL** — Relational database for users and sync metadata
- **Qdrant** — Vector database for hybrid search
- **Memgraph** — Graph database for knowledge relationships
- **Metatron** — Main FastAPI application

### 4. Verify services are running

```bash
docker-compose ps
```

All services should show status `healthy` or `running`.

### 5. Check application logs

```bash
docker-compose logs -f metatron
```

Wait until you see `Application startup complete`.

### 6. Open the application

Visit `http://localhost:8000` in your browser.

## Troubleshooting

### Python 3.12 Not Found

The installer requires Python 3.12 or newer. You may have an older version installed.

**Check your version:**
```bash
python3 --version
python --version
```

**Install Python 3.12+:**
- macOS: `brew install python@3.12`
- Ubuntu/Debian: `sudo apt-get install python3.12 python3.12-venv`
- Windows: [Download from python.org](https://www.python.org/downloads/)
- Or use a version manager: [pyenv](https://github.com/pyenv/pyenv) or [conda](https://www.anaconda.com/)

After installing, verify: `python3 --version`

### Docker Not Found

Docker is required to run Metatron's services (database, vector store, etc.).

**Install Docker:**
- macOS/Windows: [Docker Desktop](https://www.docker.com/products/docker-desktop)
- Linux: [Docker Engine](https://docs.docker.com/engine/install/)

After installing, verify:
```bash
docker --version
docker run hello-world  # Quick test
```

### Permission Denied on install.sh

If you see `Permission denied`, make the script executable:

```bash
chmod +x install.sh
bash install.sh
```

### docker-compose Command Not Found

If `docker-compose` doesn't exist, try the newer command format:

```bash
docker compose up -d  # Note: no hyphen
```

Or [install Docker Compose](https://docs.docker.com/compose/install/):
- macOS: `brew install docker-compose`
- Ubuntu/Debian: `sudo apt-get install docker-compose`

### Clone Failed: "Repository not found"

Check that:
1. The GitHub URL is correct: `https://github.com/openclaw/metatron.git`
2. You have internet connectivity: `ping github.com`
3. Your SSH keys are set up (if using SSH): `ssh -T git@github.com`

### docker-compose up Fails

**Check Docker daemon is running:**
```bash
docker ps
```

**Check logs for more detail:**
```bash
docker-compose logs
```

**Common issues:**
- Port 8000 is already in use: `lsof -i :8000` (macOS/Linux)
- Disk space full: `df -h`
- Out of memory: Docker needs ~4GB free RAM

## Next Steps

Once installation completes, you'll see:

```
Next steps:
  1. Check service health: docker-compose logs -f
  2. Open browser: http://localhost:8000
  3. Add configuration tokens to .env (if using bots)
  4. See docs/QUICKSTART.md for first steps
```

### 1. Configure Bots (Optional)

If you want to use Telegram, Discord, or Slack bots:

1. Edit `.env` and add your bot tokens:
   ```bash
   # Telegram (from @BotFather)
   TELEGRAM_BOT_TOKEN=...
   
   # Discord (from Developer Portal)
   DISCORD_BOT_TOKEN=...
   
   # Slack (from OAuth & Permissions)
   SLACK_BOT_TOKEN=...
   SLACK_APP_TOKEN=...
   ```

2. Restart the application:
   ```bash
   docker-compose restart metatron
   ```

### 2. Verify Application

Check the API health:

```bash
curl http://localhost:8000/health
```

Expected response: `{"status":"healthy"}`

### 3. First Steps

See `docs/QUICKSTART.md` for:
- Syncing your first data source (Confluence, Jira, Notion)
- Asking questions of your knowledge base
- Using bot commands

## Advanced Configuration

See `docs/CONFIGURATION.md` for:
- LLM provider setup (Ollama, DeepSeek, OpenRouter)
- Connector configuration (Confluence, Jira, Notion, custom MCP)
- Environment variables reference
- Production deployment

## Getting Help

- **Issue Tracker:** [GitHub Issues](https://github.com/openclaw/metatron/issues)
- **Documentation:** See `docs/` directory
- **Architecture:** See `CLAUDE.md`

## Uninstalling

To remove Metatron:

```bash
# Stop and remove containers
docker-compose down -v

# Remove installation directory
rm -rf ~/.metatron

# Or, if you cloned to a custom location:
cd /path/to/metatron
docker-compose down -v
```

---

**Questions or issues?** Please open an issue on GitHub or check `docs/TROUBLESHOOTING.md`.
