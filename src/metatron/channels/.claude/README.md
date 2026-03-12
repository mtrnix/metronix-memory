# Channels

## Overview
L5 — messaging platform adapters. Receives messages from Telegram, Discord, and Slack,
routes them through `AgentRouter` (L4), and sends responses back. Each channel manages
its own event loop / polling mechanism.

## Files

### `telegram.py`
`TelegramChannel` — aiogram 3.x bot with long-polling.

`__init__(bot_token, router: AgentRouter, settings)`
`start()` — initializes `Bot` + `Dispatcher`, registers message handler, starts `dp.start_polling()`
`stop()` — `dp.stop_polling()`

Message handler flow:
1. Receives `types.Message` from aiogram
2. Builds `IncomingMessage(channel="telegram", channel_user_id=str(msg.from_user.id), ...)`
3. Sends typing indicator (`ChatAction.TYPING`)
4. Routes via `asyncio.to_thread(router.route, incoming_message)`
5. Sends response via `bot.send_message()` with `ParseMode.MARKDOWN_V2`
6. On Markdown parse error → fallback to `_markdown_to_html()` → fallback to plain text

`_markdown_to_html(text) -> str` — converts basic Markdown to Telegram HTML.
`_split_message(text, max_length=4096) -> list[str]` — splits long responses at paragraph boundaries.

Config: `TELEGRAM_BOT_TOKEN`

### `discord.py`
`DiscordChannel` — discord.py bot.

`__init__(bot_token, router: AgentRouter)`
`start()` — `client.run(token)` (blocking, runs in thread)
`stop()` — `asyncio.run_coroutine_threadsafe(client.close(), ...)`

Registers `on_message` handler: ignores bot messages, routes user messages via `asyncio.to_thread(router.route, ...)`.
Responses split at `_DC_MAX_LENGTH = 2000` characters.
Mention prefix: responds when bot is `@mentioned` or DM'd.

Config: `DISCORD_BOT_TOKEN`

### `slack.py`
`SlackChannel` — Slack Bolt app with Socket Mode.

`__init__(bot_token, app_token, signing_secret, router: AgentRouter)`
`start()` — initializes `App` + `SocketModeHandler`, starts Socket Mode connection
`stop()` — closes SocketModeHandler

Registers `@app.message()` handler: builds `IncomingMessage`, routes via `asyncio.to_thread(router.route, ...)`.
Thread-aware: uses `thread_ts` for threaded replies.
Responses split at `_SLACK_MAX_LENGTH = 3000` characters using Block Kit text blocks.

Config: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_SIGNING_SECRET`

## Key Patterns
- **Async bridge** — all channels are async, `AgentRouter.route()` is sync; bridge via `asyncio.to_thread()`
- **Long message splitting** — all channels split at platform-specific limits (4096 TG, 2000 Discord, 3000 Slack) at paragraph boundaries
- **Markdown fallback chain** (Telegram only): MarkdownV2 → HTML → plain text — Telegram's strict MarkdownV2 parsing fails often
- **Unified message shape** — all channels translate to/from `IncomingMessage`/`OutgoingMessage` from core.models

## Dependencies
- **Depends on**: `core.models` (IncomingMessage, OutgoingMessage), `core.config` (Settings), `agent.router` (AgentRouter)
- **Depended on by**: `app.py` (top-level entry — channels started in `asyncio.gather()` with API)
