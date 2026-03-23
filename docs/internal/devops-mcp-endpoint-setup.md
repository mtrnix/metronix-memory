# Задача: включить /mcp эндпоинт на metatrondev

## Контекст

Metatron предоставляет MCP (Model Context Protocol) эндпоинт на `/mcp` для подключения внешних AI-ассистентов. Сейчас reverse proxy блокирует этот путь — GET отдаёт фронтенд (SPA), POST возвращает 405.

По заголовку `server: nginx/1.29.6` видно что запросы проходят через nginx, но возможно используется Caddy — примеры ниже для обоих.

## Что нужно сделать

### 1. Добавить проксирование /mcp в reverse proxy

Путь `/mcp` должен проксироваться на бэкенд Metatron (тот же upstream, что и `/api/`).

**Вариант: Caddy (Caddyfile)**

Добавить рядом с существующим правилом для `/api/`:

```caddyfile
handle /mcp {
    reverse_proxy metatron-backend:8000
}
```

**Вариант: Nginx**

Добавить `location` блок рядом с существующим правилом для `/api/`:

```nginx
location /mcp {
    proxy_pass http://metatron-backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

В обоих случаях вместо `metatron-backend:8000` указать реальный upstream.

**Важно:** правило для `/mcp` должно стоять **перед** SPA catch-all (который отдаёт `index.html` для всех неизвестных путей), чтобы `/mcp` матчился первым.

### 2. Добавить переменную окружения

Добавить в окружение контейнера/сервиса Metatron:

```
METATRON_MCP_API_KEY=<сгенерировать безопасный ключ>
```

Генерация ключа:
```bash
openssl rand -hex 32
```

Этот ключ будут использовать внешние клиенты для аутентификации на `/mcp`. Без него эндпоинт открыт всем (dev-режим).

## Проверка

После деплоя обоих изменений:

```bash
# Должен вернуть ошибку MCP-протокола (не HTML, не 405) — proxy работает правильно
curl -X POST https://ui.metatrondev.ximi.group/mcp

# Должен вернуть 401 (нужна авторизация) — ключ проверяется
curl -X POST -H "Content-Type: application/json" \
     https://ui.metatrondev.ximi.group/mcp

# НЕ должен вернуть 401 — ключ работает
curl -X POST -H "Authorization: Bearer <ваш-ключ>" \
     -H "Content-Type: application/json" \
     https://ui.metatrondev.ximi.group/mcp
```

## Заметки

- Эндпоинт `/mcp` принимает методы GET, POST и DELETE
- Существующие API-эндпоинты не затрагиваются — добавляется только новый путь
- Аутентификация `METATRON_MCP_API_KEY` работает независимо от `AUTH_ENABLED` и JWT-логина
