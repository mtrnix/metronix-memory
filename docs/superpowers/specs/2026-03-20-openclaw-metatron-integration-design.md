# OpenClaw → Metatron Integration Design

**Date:** 2026-03-20
**Status:** Draft
**Goal:** Подключить OpenClaw (персональный AI-ассистент) к Metatron (корпоративная RAG-система) как knowledge base через MCP.

## Overview

OpenClaw — self-hosted персональный AI-ассистент, развёрнут на сервере A.
Metatron — корпоративная RAG-система, развёрнута на сервере B.

OpenClaw-агент должен искать ответы в корпоративной базе знаний Metatron. Начинаем с инструмента `metatron_search` и одного workspace.

```
OpenClaw (сервер A) → HTTP → Metatron /mcp (сервер B)
```

Два варианта интеграции:
- **Вариант A** — `mcp-remote` (нативные MCP-инструменты) — рекомендуемый
- **Вариант B** — `MCPorter` (CLI + skill + daemon)

## Prerequisites: подготовка Metatron

### 1. Фикс аутентификации /mcp (ВЫПОЛНЕНО)

При исследовании обнаружено: `METATRON_MCP_API_KEY` **не проверялся** для `/mcp`
при запуске через `create_app()` (основной режим). Валидация работала только
в standalone `run_http()` режиме.

**Фикс:** ветка `fix/mcp-api-key-auth` — middleware теперь перехватывает `/mcp`
независимо от `AUTH_ENABLED` и валидирует через `METATRON_MCP_API_KEY`.
Также исправлено timing-safe сравнение ключей (`hmac.compare_digest`).

**Статус:** фикс реализован и протестирован (6 тестов), ожидает мержа.

### 2. Настроить API-ключ

```bash
# В .env или переменных окружения Metatron
METATRON_MCP_API_KEY=your-secure-key-here
```

Без этого MCP принимает все запросы без аутентификации (dev-режим).

### 3. Обеспечить доступность /mcp извне

Metatron поддерживает streamable-http транспорт на `/mcp`.
Убедиться что эндпоинт доступен извне (firewall, reverse proxy).

### 4. Узнать workspace ID

MCP-инструменты принимают `workspace_id` как параметр. Получить ID:

```bash
curl https://metatron-server:8000/api/v1/workspaces
```

### 5. Проверить доступность

```bash
curl -H "Authorization: Bearer your-secure-key-here" \
     https://metatron-server:8000/mcp
```

## Вариант A: mcp-remote (рекомендуемый)

### Что это

npm-пакет, который OpenClaw запускает как stdio-subprocess. Внутри открывает
HTTP-соединение к удалённому MCP-серверу. Отдельно поднимать не нужно.

- **GitHub:** https://github.com/geelen/mcp-remote (1,300+ stars)
- **Требования:** Node.js (npx) на сервере OpenClaw

### Как работает

1. OpenClaw-агент решает вызвать tool `metatron_search`
2. OpenClaw запускает `npx mcp-remote` как subprocess (stdio)
3. `mcp-remote` открывает HTTP-соединение к Metatron `/mcp`
4. Проксирует запрос, возвращает ответ через stdio
5. Subprocess живёт пока OpenClaw держит сессию

Агент видит Metatron tools как **свои нативные инструменты** — не знает
что за ними стоит прокси. Никакого специального промпта не нужно.

### Настройка

В `openclaw.json` на сервере OpenClaw:

```json
{
  "mcp": {
    "servers": {
      "metatron": {
        "command": "npx",
        "args": [
          "-y", "mcp-remote",
          "https://metatron-server:8000/mcp",
          "--header", "Authorization:Bearer ${METATRON_MCP_KEY}"
        ],
        "env": {
          "METATRON_MCP_KEY": "your-secure-key-here"
        }
      }
    }
  }
}
```

### Проверка

```bash
openclaw gateway restart
openclaw mcp list
openclaw mcp show metatron
```

Агент должен увидеть: `metatron_search`, `metatron_get`, `metatron_store`,
`metatron_sync`, `metatron_status`.

### Тест

Отправить агенту сообщение в любом канале:
> "Найди в базе знаний информацию о VPN"

Агент автоматически вызовет `metatron_search` и вернёт ответ с источниками.

### Latency

- Первый запуск: ~2-3 сек (npx скачивает пакет)
- Повторные: ~200-500мс (пакет в кеше)
- HTTP к Metatron: ~50-200мс (зависит от сети)

### Ограничения

- Нет persistent connection — subprocess пересоздаётся при новой сессии
- OpenClaw пока поддерживает только stdio MCP — `mcp-remote` решает это

## Вариант B: MCPorter

### Что это

CLI-инструмент + daemon для работы с MCP-серверами. Встроен как skill в OpenClaw.

- **GitHub:** https://github.com/steipete/mcporter
- **Требования:** Node.js + `npm install -g mcporter`

### Как работает

Агент использует встроенный скилл `mcporter` и вызывает CLI-команды. Агент
должен **сознательно решить** использовать mcporter — для этого ему нужен
skill-промпт, объясняющий когда и как вызывать Metatron.

### Установка

```bash
npm install -g mcporter
```

### Настройка

В `~/.mcporter/mcporter.json` или `config/mcporter.json`:

```json
{
  "servers": {
    "metatron": {
      "url": "https://metatron-server:8000/mcp",
      "headers": {
        "Authorization": "Bearer your-secure-key-here"
      }
    }
  }
}
```

### Проверка

```bash
mcporter list metatron
mcporter call metatron.metatron_search query="VPN" workspace_id="your-workspace-id"
```

### Daemon (persistent connection)

```bash
mcporter daemon start    # соединение постоянно живое
mcporter daemon status   # проверить подключение
mcporter daemon stop     # остановить
```

### Ограничения

- Инструменты не нативные MCP-tools — вызовы идут через CLI
- Агент должен "знать" про mcporter через skill prompt
- Зависимость от отдельного пакета

## Сравнение

| Критерий | mcp-remote | MCPorter |
|----------|-----------|---------|
| **Простота настройки** | Проще — только конфиг OpenClaw | Установка + конфиг + skill |
| **Нативность для агента** | Нативные MCP tools | CLI через skill |
| **Расход токенов** | ~150-250 на вызов | ~700-1400 на вызов (3-5x больше) |
| **Расширяемость** | Автоматически — новые tools видны сразу | Нужно обновлять skill |
| **Persistent connection** | Нет (reconnect ~200-500мс) | Да (daemon) |
| **Отладка** | Менее прозрачно | Удобнее (CLI) |
| **Знание агента** | Не нужно, видит tools нативно | Нужен skill prompt |

### Расход токенов (детали)

**mcp-remote:** tool definition в system prompt как JSON-schema (~100-200 токенов
на tool), вызов — tool_use блок (~30-50 токенов). Итого ~150-250 на вызов.

**MCPorter:** скилл в промпте (~500-1000 токенов), CLI-команда + парсинг ответа
(~100-200 токенов), рассуждения о синтаксисе (~50-200 токенов). Итого ~700-1400.

## Рекомендации

**Когда выбрать mcp-remote:**
- Основной production-сценарий
- Экономия токенов важна
- "Поставил и забыл"

**Когда выбрать MCPorter:**
- Нужен persistent connection (высокая нагрузка, latency критичен)
- Отладка вызовов из CLI
- Управление несколькими MCP-серверами

**Рекомендация:** начать с **mcp-remote** как основной вариант. MCPorter — для
отладки и как fallback если нужен daemon.

## Доступные инструменты Metatron (MCP)

| Tool | Описание |
|------|----------|
| `metatron_search` | Гибридный RAG-поиск (vector + BM25 + graph) |
| `metatron_get` | Получить конкретный документ по ID |
| `metatron_store` | Индексировать новый документ |
| `metatron_sync` | Запустить синхронизацию коннектора |
| `metatron_status` | Статистика workspace |

Начинаем с `metatron_search`, расширяем по необходимости.

## Known Issues

- **AUTH_ENABLED** — рассмотреть удаление этой env-переменной в отдельной задаче.
  Сейчас `AUTH_ENABLED=false` по умолчанию, но login всё равно работает через UI
  (middleware просто не валидирует JWT). Это создаёт путаницу.
