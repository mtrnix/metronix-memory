# LibreChat Integration

LibreChat can use Metronix Memory through the OpenAI-compatible API.

Use:

```text
Base URL: http://localhost:8001/v1
API key:  <METATRON_OPENAI_COMPAT_KEY>
Model:    metatron-rag-<workspace_id>
```

Metronix Memory is not a raw LLM proxy on this endpoint. It runs retrieval over the selected
workspace and returns grounded answers.
