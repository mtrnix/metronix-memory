# Ollama + GLM or Qwen

## Recommended path

Use Ollama as the local model host and point Metatron at it with `LLM_PROVIDER=ollama`.

If you want the safer first setup, start with Qwen. GLM may work fine, but Qwen is the
lower-drama option for local instruction models.

## Option A: bundled Ollama

Use the built-in Ollama service from `docker-compose.full.yml`:

```ini
LLM_PROVIDER=ollama
```

Start the stack:

```bash
docker compose -f docker-compose.full.yml up -d --build
```

This exposes Ollama on host port `11435`.

## Option B: external Ollama

If Ollama already runs outside the Compose stack:

```ini
LLM_PROVIDER=ollama
OLLAMA_HOST=http://your-ollama-host:11434
```

## Pick a chat model

Metatron supports setting a dedicated Ollama chat model:

```ini
OLLAMA_CHAT_MODEL=qwen2.5:7b-instruct
OLLAMA_LLM_MODEL=qwen2.5:7b-instruct
```

or:

```ini
OLLAMA_CHAT_MODEL=glm4:9b
OLLAMA_LLM_MODEL=glm4:9b
```

The exact tag depends on what you pulled into Ollama.

## Pull models

Examples:

```bash
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text
```

or:

```bash
ollama pull glm4:9b
ollama pull nomic-embed-text
```

## Verify

Check the API:

```bash
curl http://localhost:8001/health
curl http://localhost:11435/api/tags
```

## Recommendation

Start with:

- embedding model: `nomic-embed-text`
- chat model: `qwen2.5:7b-instruct`

Once the stack is stable, try GLM if you want. First make it boring, then make it fancy.
