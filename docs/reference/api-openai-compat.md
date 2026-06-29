# OpenAI-Compatible API

Metronix Memory exposes an OpenAI-compatible API for clients such as Open WebUI and LibreChat.

Base URL:

```text
http://localhost:8001/v1
```

Common endpoints:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `GET /v1/openapi.json`

This surface is not a raw LLM proxy. It runs retrieval over Metronix Memory knowledge and returns
grounded answers.

For Open WebUI setup, see [`../integrations/openwebui.md`](../integrations/openwebui.md).
For LibreChat setup, see [`../integrations/librechat.md`](../integrations/librechat.md).
