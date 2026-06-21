# Examples

Working usage examples for Metatron Core. Each is self-contained and documented.

## Prerequisites

```bash
pip install httpx
docker compose up -d   # start Metatron + databases
```

## Examples

| File | What it shows |
|---|---|
| [`quickstart.sh`](quickstart.sh) | Health check, sync, and search in 3 steps (bash) |
| [`search_example.py`](search_example.py) | Search your knowledge base from Python |
| [`memory_example.py`](memory_example.py) | Store and retrieve agent memory (fact, preference, pinned) |

## Running

```bash
# Bash quickstart
bash examples/quickstart.sh

# Python examples
export METATRON_API_KEY=your-api-key
python examples/search_example.py "what is the Q2 budget?"
python examples/memory_example.py
```

## More Integrations

- **Hermes Agent:** Connect via MCP — see [docs/HERMES_INTEGRATION.md](../docs/HERMES_INTEGRATION.md)
- **Claude Desktop / Cursor:** Point MCP client at `python -m metatron.mcp`
- **OpenWebUI:** Add as OpenAI-compatible endpoint at `http://localhost:8000/v1`
