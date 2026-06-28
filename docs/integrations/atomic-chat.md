# Atomic Chat / Open WebUI + Ollama

## Recommended path

If you want a local self-hosted chat UI quickly, the easiest route is:

- Metatron Core
- built-in or external Ollama
- Open WebUI

That is the practical "Atomic Chat" equivalent in this repo today.

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

## Internal wiring

Inside Docker, Open WebUI talks to:

```text
http://metatron-core:8000/v1
```

From your host machine, Metatron is exposed at:

```text
http://localhost:8001/v1
```

## Verify

1. Confirm `curl http://localhost:8001/health`
2. Open `http://localhost:3080`
3. Send a test question through the UI

## Recommendation

If you want the shortest path to "local model + memory + chat UI," this is it.
Not glamorous, but neither is a forklift, and forklifts get work done.
