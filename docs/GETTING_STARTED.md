# Getting Started with Metatron Core

This guide will help you set up and run Metatron Core on your local machine.

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.12 or 3.13**
- **Docker** and **Docker Compose**
- **Git**
- **Make** (usually pre-installed on macOS and Linux)

## Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/metatron-core.git
cd metatron-core
```

### 2. Configure Environment Variables

Copy the example environment file and configure it:

```bash
cp .env.example .env
```

Open `.env` in your editor and configure the following key variables:

- **DATABASE_URL**: PostgreSQL connection string (default: `postgresql://metatron:metatron@localhost:5432/metatron`)
- **QDRANT_URL**: Qdrant vector database URL (default: `http://localhost:6333`)
- **MEMGRAPH_URL**: Memgraph graph database URL (default: `bolt://localhost:7687`)
- **OLLAMA_URL**: Ollama API endpoint (default: `http://localhost:11434`)
- **ENCRYPTION_KEY**: Generate a secure key for encrypting connection credentials
- **SECRET_KEY**: Secret key for API authentication
- **ENVIRONMENT**: Set to `development` for local dev, `production` for production

### 3. Start Infrastructure Services

Start all required backend services using Docker Compose:

```bash
docker compose up -d
```

This will start:
- PostgreSQL (port 5432)
- Qdrant vector database (port 6333)
- Memgraph graph database (port 7687)
- Ollama LLM service (port 11434)

Verify services are running:

```bash
docker compose ps
```

### 4. Pull Required Ollama Models

Download the embedding and LLM models:

```bash
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull llama3.1:8b
```

This may take several minutes depending on your internet connection.

### 5. Install Python Dependencies

Create a virtual environment and install dependencies:

```bash
make setup
```

This command will:
- Create a Python virtual environment
- Install all required packages
- Set up development tools

### 6. Run Database Migrations

Initialize the database schema:

```bash
make migrate
```

### 7. Start the Application

Launch the unified server (API + Telegram/Discord bots):

```bash
make dev
```

This starts the API server and any configured bots (Telegram, Discord) in a single process.
Bots are only started if their tokens are set in `.env`.

The API will be available at `http://localhost:8000`.

API documentation will be available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## First Steps

Once the server is running, try these basic operations:

### 1. Create a Workspace

```bash
curl -X POST http://localhost:8000/api/v1/workspaces \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My First Workspace",
    "description": "Testing Metatron Core"
  }'
```

Save the workspace `id` from the response.

### 2. Create a Connection

```bash
curl -X POST http://localhost:8000/api/v1/connections \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "YOUR_WORKSPACE_ID",
    "source_type": "slack",
    "config": {
      "token": "xoxb-your-slack-token",
      "channels": ["general"]
    }
  }'
```

Save the connection `id` from the response.

### 3. Trigger a Sync

```bash
curl -X POST http://localhost:8000/api/v1/connections/YOUR_CONNECTION_ID/sync
```

### 4. Query Your Data

Use the query API endpoint or integrate with a messenger bot to interact with your synced data.

## Troubleshooting

### Port Conflicts

If you encounter port conflicts:

1. Check which process is using the port:
   ```bash
   lsof -i :8000  # or whichever port is conflicting
   ```

2. Either stop the conflicting service or change the port in `docker-compose.yml` or `.env`

### Ollama Model Pull Fails

If model downloads fail:

1. Check Docker container logs:
   ```bash
   docker compose logs ollama
   ```

2. Verify network connectivity:
   ```bash
   docker compose exec ollama curl -I https://ollama.ai
   ```

3. Try pulling models manually:
   ```bash
   docker compose exec ollama ollama pull nomic-embed-text
   ```

### Migration Errors

If database migrations fail:

1. Check PostgreSQL is running:
   ```bash
   docker compose ps postgres
   ```

2. Verify database connection:
   ```bash
   docker compose exec postgres psql -U metatron -d metatron -c "SELECT version();"
   ```

3. Reset the database (WARNING: destroys all data):
   ```bash
   make reset-db
   make migrate
   ```

### Docker Compose Issues

If services fail to start:

1. Check Docker daemon is running:
   ```bash
   docker info
   ```

2. View service logs:
   ```bash
   docker compose logs -f
   ```

3. Restart services:
   ```bash
   docker compose down
   docker compose up -d
   ```

## Development Tips

### Running Tests

Run the test suite:

```bash
make test
```

Run tests with coverage:

```bash
make test-coverage
```

### Code Quality

Lint your code:

```bash
make lint
```

Format your code:

```bash
make format
```

Run type checking:

```bash
make typecheck
```

### Development Workflow

1. Create a feature branch:
   ```bash
   git checkout -b feature/my-feature
   ```

2. Make your changes and test:
   ```bash
   make test
   make lint
   ```

3. Commit and push:
   ```bash
   git add .
   git commit -m "Add my feature"
   git push origin feature/my-feature
   ```

### Useful Make Commands

- `make help` - Show all available commands
- `make clean` - Clean up temporary files
- `make shell` - Start a Python shell with app context
- `make logs` - Tail application logs
- `make db-shell` - Connect to PostgreSQL database

## Next Steps

- Read the [API Documentation](./API.md) to learn about available endpoints
- Explore the [Architecture Guide](./ARCHITECTURE.md) to understand the system design
- Check out the [Contributing Guide](../CONTRIBUTING.md) to contribute to the project

## Getting Help

If you encounter issues:

1. Check the [Troubleshooting](#troubleshooting) section above
2. Review the project documentation in the `docs/` directory
3. Search existing GitHub issues
4. Open a new issue with details about your problem
