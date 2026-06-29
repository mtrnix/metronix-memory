# Open WebUI + Ollama (local chat)

## Recommended path

If you want a local self-hosted chat UI quickly, use:

- Metronix Memory (backend)
- built-in or external Ollama
- Open WebUI (`--profile openwebui`)

## Start the stack

```bash
docker compose -f docker-compose.full.yml --profile openwebui up -d --build
```

Open:

```text
http://localhost:3080
```

## Ollama setup

Built-in Ollama:

```ini
LLM_PROVIDER=ollama
```

External Ollama:

```ini
LLM_PROVIDER=ollama
OLLAMA_HOST=http://your-ollama-host:11434
```

Recommended first model:

```ini
OLLAMA_CHAT_MODEL=qwen2.5:7b-instruct
OLLAMA_LLM_MODEL=qwen2.5:7b-instruct
```

## Internal vs host URLs

Inside Docker, Open WebUI talks to:

```text
http://metronix-core:8000/v1
```

From your host machine, Metronix Memory is exposed at:

```text
http://localhost:8000/v1
```

Use the host URL when configuring clients outside the Compose network.

## Verify

1. Confirm `curl http://localhost:8000/health`
2. Open `http://localhost:3080`
3. Send a test question through the UI

## Troubleshooting

**UI not loading:** Check that the `openwebui` profile was included when starting the stack. Run `docker compose -f docker-compose.full.yml --profile openwebui ps` to confirm the container is running.

**MCP server not responding:** Verify `curl http://localhost:8000/health` returns OK and that `METRONIX_MCP_API_KEY` in your `.env` matches the key configured in the client.

**Tools not appearing after registration:** Restart the client after adding the MCP server — most clients load MCP servers only at startup.

**Authentication errors:** Confirm the `Authorization: Bearer <key>` header is set correctly. The key must match `METRONIX_MCP_API_KEY` in `.env`.
