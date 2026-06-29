<!-- TODO: This guide needs a full rewrite. Currently missing: prerequisites section, numbered setup steps. -->

# Open WebUI Integration

Open WebUI connects to Metronix Memory through the OpenAI-compatible API.

Start the profile:

```bash
docker compose -f docker-compose.full.yml --profile openwebui up -d --build
```

Open `http://localhost:3080`.

The bundled profile points Open WebUI at:

```text
http://metatron-core:8000/v1
```

For non-local or shared deployments, set a strong `METATRON_OPENAI_COMPAT_KEY` and
enable authentication in Open WebUI.

## Verify

After setup, confirm the connection works:

1. Open `http://localhost:3080` in your browser.
2. Start a new conversation and send a test message.
3. Confirm a grounded response is returned from Metronix Memory.

If the UI does not load, run `curl http://localhost:8001/health` to check the stack.

## Troubleshooting

**UI not loading at `http://localhost:3080`:** Check that the `openwebui` profile was included when starting the stack. Run `docker compose -f docker-compose.full.yml --profile openwebui ps` to confirm the container is running.

**No response from the model:** Verify `METATRON_OPENAI_COMPAT_KEY` is set in `.env` and that the Open WebUI model is pointed at the correct internal URL (`http://metatron-core:8000/v1`).

**Authentication errors:** For shared deployments, confirm the API key in Open WebUI matches `METATRON_OPENAI_COMPAT_KEY` in `.env`.
