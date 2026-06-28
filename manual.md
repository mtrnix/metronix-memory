# Metronix Core Manual Install

This is the short version. If you want the full deployment reference, troubleshooting, or
port details, use [`install.md`](install.md).

## 1. Clone

```bash
git clone -b develop https://github.com/mtrnix/metatroncore.git
cd metatroncore
```

## 2. Verify Docker

```bash
docker --version
docker compose version 2>/dev/null || docker-compose --version
docker info >/dev/null 2>&1 && echo "daemon OK" || echo "START DOCKER DAEMON"
```

If Docker is missing:

- macOS: <https://docs.docker.com/desktop/setup/install/mac-install/>
- Linux: <https://docs.docker.com/engine/install/>
- Windows: <https://docs.docker.com/desktop/setup/install/windows-install/>

On macOS, if `docker compose build` fails with `permission denied`, fix Docker Desktop's
ownership drift:

```bash
sudo chown -R $(whoami):staff ~/.docker
```

## 3. Create `.env`

```bash
cp .env.example .env
```

Pick one provider.

DeepSeek:

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-your-deepseek-key
```

OpenRouter:

```ini
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-your-openrouter-key
```

Built-in Ollama:

```ini
LLM_PROVIDER=ollama
```

External Ollama:

```ini
LLM_PROVIDER=ollama
OLLAMA_HOST=http://your-ollama-host:11434
```

Custom OpenAI-compatible provider:

```ini
LLM_PROVIDER=custom
CUSTOM_LLM_URL=https://your-llm-endpoint/v1
CUSTOM_LLM_API_KEY=your-key
```

Create an MCP key:

```bash
openssl rand -hex 32
```

Add it to `.env`:

```ini
METATRON_MCP_API_KEY=<paste-the-generated-token>
```

## 4. Start

Backend only:

```bash
docker compose -f docker-compose.full.yml up -d --build
```

Backend plus Open WebUI:

```bash
docker compose -f docker-compose.full.yml --profile openwebui up -d --build
```

## 5. Verify

```bash
docker compose -f docker-compose.full.yml ps
curl http://localhost:8001/health
```

If Open WebUI is enabled, open:

```text
http://localhost:3080
```

## 6. Pick a runtime guide

Once the backend is running, choose the integration you actually care about:

- [`docs/integrations/hermes-agent.md`](docs/integrations/hermes-agent.md)
- [`docs/integrations/openclaw.md`](docs/integrations/openclaw.md)
- [`docs/integrations/ollama-local-models.md`](docs/integrations/ollama-local-models.md)
- [`docs/integrations/claude-code.md`](docs/integrations/claude-code.md)
- [`docs/integrations/codex.md`](docs/integrations/codex.md)
- [`docs/integrations/opencode.md`](docs/integrations/opencode.md)
- [`docs/integrations/pi.md`](docs/integrations/pi.md)
- [`docs/integrations/langchain.md`](docs/integrations/langchain.md)
- [`docs/integrations/sdk-python.md`](docs/integrations/sdk-python.md)
- [`docs/integrations/sdk-go.md`](docs/integrations/sdk-go.md)
- [`docs/integrations/n8n.md`](docs/integrations/n8n.md)
- [`docs/integrations/nanoclaw.md`](docs/integrations/nanoclaw.md)
- [`docs/integrations/nanobot.md`](docs/integrations/nanobot.md)
- [`docs/integrations/atomic-chat.md`](docs/integrations/atomic-chat.md)
