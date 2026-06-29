# Configuration Reference

Metronix reads configuration from environment variables and `.env`.

For a standard Docker install, copy:

```bash
cp .env.example .env
```

Set at least:

- `LLM_PROVIDER`
- the selected provider API key, unless using bundled Ollama
- `METRONIX_MCP_API_KEY` when using MCP

For production and staging, also set non-default values for:

- `METRONIX_SECRET_KEY`
- `AUTH_PASSWORD`
- `POSTGRES_PASSWORD`
- `FERNET_KEY`
- `METRONIX_MCP_API_KEY`

See `../../install.md` and `.env.example` for full details.
