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
