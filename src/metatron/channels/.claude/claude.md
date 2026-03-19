# Channels

## Overview
L5 — messaging platform adapters. Receives messages from Telegram, Discord, and Slack,
routes them through `AgentRouter` (L4), and sends responses back. Each channel manages
its own event loop / polling mechanism.

## Configuration Model
**All channel credentials are stored in the database** (encrypted with Fernet), not in env vars.
The `config.py` Settings class no longer contains channel-specific env vars (TELEGRAM_BOT_TOKEN, etc.).

Channels are started dynamically by `ChannelManager` at app startup:
1. Query DB for enabled connections with `category="channel"`
2. Decrypt config (bot tokens) via Fernet
3. Create and start the appropriate channel instance
4. Gracefully stop all channels on app shutdown

Channel types and their config fields (from `connectors/schemas.py`):
- **telegram**: `bot_token`
- **discord**: `bot_token`
- **slack**: `bot_token`, `app_token`, `signing_secret` (optional)

## Files

### `manager.py`
`ChannelManager` — dynamic start/stop of messaging channels from DB config.

`__init__(router: AgentRouter)` — takes a shared router instance.

Key methods:
- `start_channels_from_db(postgres_dsn, fernet_key, default_workspace_id)` — queries DB for enabled
  channel connections, decrypts config, starts each channel as a background task. Returns count started.
- `start_channel(connection_id, connector_type, config)` — start a single channel with decrypted config.
- `stop_channel(connection_id)` — gracefully stop a running channel.
- `stop_all()` — stop all running channels (called at shutdown).
- `restart_channel(connection_id, connector_type, config)` — stop + start with new config.

Internal state:
- `_running: dict[str, Any]` — connection_id → channel instance
- `_tasks: dict[str, asyncio.Task]` — connection_id → background task

`_create_channel(connector_type, config, router)` — factory function that creates
TelegramChannel, DiscordChannel, or SlackChannel from a config dict.

`_run_channel_safe(connection_id, connector_type, channel)` — wraps `channel.start()`
with crash isolation (logs error, doesn't propagate).

### `telegram.py`
`TelegramChannel` — aiogram 3.x bot with long-polling.

`__init__(bot_token, router: AgentRouter, workspace_id=None)`
`start()` — initializes `Bot` + `Dispatcher`, registers message handler, starts `dp.start_polling()`
`stop()` — `dp.stop_polling()` + close bot session

Message handler flow:
1. Receives `types.Message` from aiogram
2. Sends typing indicator (`ChatAction.TYPING`)
3. Routes via `asyncio.to_thread(router.route, ...)` with workspace_id
4. Sends response via `bot.send_message()` with Markdown → HTML → plain fallback

`_markdown_to_html(text) -> str` — converts basic Markdown to Telegram HTML.
`_split_message(text, max_length=4096) -> list[str]` — splits long responses at paragraph boundaries.

### `discord.py`
`DiscordChannel` — discord.py bot.

`__init__(bot_token, router: AgentRouter, workspace_id=None)`
`start()` — `client.start(token)` (async)
`stop()` — `client.close()`

Registers `on_message` handler: ignores bot messages, routes user DMs via `asyncio.to_thread(router.route, ...)`.
Responses split at `_DC_MAX_LENGTH = 2000` characters.

### `slack.py`
`SlackChannel` — Slack Bolt app with Socket Mode.

`__init__(bot_token, app_token, router: AgentRouter, workspace_id=None)`
`start()` — initializes `AsyncApp` + `AsyncSocketModeHandler`, starts Socket Mode connection
`stop()` — closes handler via `close_async()`

Registers `@app.event("message")` handler: routes DM text via `asyncio.to_thread(router.route, ...)`.
File uploads downloaded via `httpx` with bot token auth.
Responses split at `_SLACK_MAX_LENGTH = 4000` characters.

## Key Patterns
- **DB-driven startup** — ChannelManager queries PostgreSQL for enabled channel connections; no env vars needed
- **Async bridge** — all channels are async, `AgentRouter.route()` is sync; bridge via `asyncio.to_thread()`
- **Long message splitting** — all channels split at platform-specific limits (4096 TG, 2000 Discord, 4000 Slack) at paragraph boundaries
- **Markdown fallback chain** (Telegram only): Markdown → HTML → plain text
- **Crash isolation** — each channel runs in its own task; a crash in one doesn't affect others
- **Graceful shutdown** — `stop_all()` called in `app.py` finally block

## Dependencies
- **Depends on**: `core.models`, `agent.router` (AgentRouter), `storage.postgres` (PostgresStore), `connectors.schemas` (CONNECTOR_SCHEMAS)
- **Depended on by**: `app.py` (top-level entry — ChannelManager started alongside API)
