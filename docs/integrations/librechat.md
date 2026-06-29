<!-- TODO: This guide needs a full rewrite. Currently missing: prerequisites section, numbered setup steps. -->

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

## Verify

After setup, confirm the connection works:

1. Open a new conversation in LibreChat.
2. Select the `metatron-rag-<workspace_id>` model.
3. Send a test message and confirm a response is returned.

If the model is not listed, check that the Base URL and API key are saved correctly and restart LibreChat.

## Troubleshooting

**Model not appearing in LibreChat:** Verify the Base URL and API key are configured correctly in LibreChat's model settings. Restart LibreChat after saving.

**API endpoint unreachable:** Run `curl http://localhost:8001/health` to confirm the stack is running.

**Authentication errors:** Confirm the API key matches `METATRON_OPENAI_COMPAT_KEY` in `.env`.
