# LibreChat Integration

LibreChat can use Metronix through the OpenAI-compatible API.

Use:

```text
Base URL: http://localhost:8000/v1
API key:  <METRONIX_OPENAI_COMPAT_KEY>
Model:    metronix-rag-<workspace_id>
```

Metronix is not a raw LLM proxy on this endpoint. It runs retrieval over the selected
workspace and returns grounded answers.
