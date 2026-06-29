---
name: OSS Cleanup Plan
overview: "Подготовить Metronix Memory к open-source публикации через безопасную поэтапную очистку: убрать внутренние артефакты, секретные/продовые следы, демо-пайплайн и конфликтующие install-доки; затем собрать понятную публичную структуру документации с README, manual.md, install.md, connecting_to_agent.md, open-core boundary и agent integration guides."
todos:
  - id: inventory-blockers
    content: Create file-by-file OSS blocker inventory for internal workflows, QA, AI dev artifacts, internal docs, and demo pipeline.
    status: completed
  - id: remove-publication-blockers
    content: Remove or privatize publication blockers and verify no private host/process artifacts remain in tracked files.
    status: completed
  - id: harden-secrets
    content: Replace risky defaults or add production startup validation; sanitize K8s/Compose examples.
    status: completed
  - id: cleanup-obsolete
    content: Delete high-confidence broken/unused files and keep legacy runtime cleanup for follow-up PRs.
    status: completed
  - id: rewrite-boundaries
    content: Remove UI-CC from install path and add public open-core boundary documentation.
    status: completed
  - id: rebuild-docs
    content: Consolidate README/manual.md/install.md/connecting_to_agent.md into the target public documentation structure with agent integration guides.
    status: completed
  - id: verify-release
    content: Run scans, lint/typecheck/tests, link checks, and full-history secret scanning before publication.
    status: in_progress
isProject: false
---

# OSS Cleanup And Documentation Plan

## Принципы Публикации

- Публичный Core может упоминать open-core модель отдельной страницей, но `README.md`, install-доки и compose-профили Core не должны устанавливать или рекламировать UI-CC как часть Core.
- Legacy runtime чистим поэтапно: сразу удаляем high-confidence мусор и внутренние артефакты; `channels/`, legacy chat и совместимые shims не ломаем в первом PR без отдельной миграции.
- `demo-data/`, `prompts/` и `seed/` не входят в первый OSS-релиз.
- Folder-path ingestion не входит в этот cleanup scope; в документации фиксируем только существующие безопасные способы загрузки данных.
- `manual.md` становится основным файлом с точки зрения последовательности действий для установки. `install.md` становится подробным справочником по развертыванию, конфигурации, ошибкам и troubleshooting. README сохраняет основную информацию о продукте, но текущий install-раздел в README заменяется на последовательность шагов из `manual.md` в краткой форме и с ссылками на полный `manual.md` / `install.md`.
- `connecting_to_agent.md` создается как отдельная инструкция: пользователь передает агенту prompt из `prompt.txt`, агент сам спрашивает недостающие параметры и подключает Metronix Memory по MCP.

## Phase 1: Publication Blockers

Удалить или приватизировать то, что нельзя публиковать:

- Internal deploy workflows: `.github/workflows/DeployENT.yml`, `.github/workflows/Deploy DEV.yml`, `.github/workflows/CIdeploy.yml`, `.github/workflows/calean_install.yml`, `.github/workflows/docker-image-ent.yml`, `.github/workflows/seed-dplat-demo.yml`.
- Internal QA harness: `tests/qa-agent/regression/`, особенно default `http://drp-m.mtrnix.com:8000`.
- AI/dev-team artifacts: `.claude/settings.local.json`, `src/metatron/**/.claude/**`; не публиковать root `CLAUDE.md` как есть, вместо этого вынести sanitized architecture/config content в public docs.
- Internal rollout/process docs: `docs/ROLLOUT_NOTES_2026-04-24.md`, `docs/TODO.md`, `docs/MEMORY_MCP_FOLLOWUPS.md`, `docs/llm_call_sites_audit.md`, `docs/NEO4J_FOLLOWUP.md`.
- Demo generation/corpus: `demo-data/`, `prompts/`, `seed/`, и связанные workflow/scripts, если они используются только для демо.

## Phase 2: Secrets And Production Hardening

Не найдено live API keys/private keys, но нужно убрать рискованные defaults и prod-like следы:

- Заменить hardcoded QA default host в `tests/qa-agent/regression/api/agents/conftest.py` на обязательный env или удалить suite.
- Добавить startup validation для production/staging defaults в `src/metatron/core/config.py`: `secret_key="change-me-in-production"`, `auth_password="metatron"`, слабые DB/MCP defaults.
- Убрать inline weak secrets из `install/metatron-k8s.yaml` и `docker-compose.full.yml`; оставить placeholders или external secret pattern.
- Исправить deploy security pattern, если workflows остаются private: `chmod 600` вместо `chmod 777`, host key verification вместо `StrictHostKeyChecking=no`.
- Добавить CI secret scanning для public repo: `gitleaks` или аналог, плюс правило на отсутствие tracked `.env`, private keys, live tokens.

## Phase 3: High-Confidence Obsolete Cleanup

Удалить или переписать только то, что статически выглядит мертвым/сломано и не является compatibility surface:

- Удалить `scripts/memgraph_syntax_test.py` или переписать под Neo4j; сейчас импортирует несуществующий `metatron.storage.memgraph`.
- Разобрать deleted `examples/*`: либо восстановить minimal public examples, либо окончательно удалить ссылки из README; `ROADMAP.md` удаляется из публичного релиза.
- Удалить/переписать stubs после проверки тестов: `src/metatron/api/routes/benchmarker.py`, unused `src/metatron/observability/tracer.py`, `src/metatron/observability/health.py`, `src/metatron/retrieval/graph_enrichment.py`, `src/metatron/retrieval/fallback.py`.
- Оставить на отдельные PR: `src/metatron/channels/`, `src/metatron/api/routes/chat.py`, `src/metatron/agent/sessions.py`, `src/metatron/api/routes/finops.py`, `src/metatron/skills/`, compatibility shims under `src/metatron/memory/freshness/`.

## Phase 4: Product Boundary Cleanup

Сделать Core понятным как OSS-продукт:

- Убрать UI-CC service/image/profile из public install artifacts: `install/docker-compose.yml`, `install/metatron-k8s.yaml`, старых install-доков (`INSTALL.md`, `docs/INSTALL.md`) и `installer/README.md`.
- Оставить `src/metatron/core/plugin.py` как нейтральный plugin extension example, но убрать private `metatron_enterprise` naming из public-facing docs или заменить на generic `acme_plugin`.
- Перенести commercial/CC explanation в одну публичную страницу `docs/product/open-core-boundaries.md`: Core, UI-KB, OpenWebUI, optional commercial Control Center outside this repo.
- Проверить `README.md`, `CHANGELOG.md`, `docs/DECISIONS.md`, `docs/LEGACY.md`, `docs/HERMES_INTEGRATION.md` на MTRNIX/Jira/private Confluence links и заменить на GitHub Issues/public wording.

## Phase 5: Public Documentation Structure

Целевая структура:

```text
README.md
manual.md
install.md
connecting_to_agent.md
CONTRIBUTING.md
SECURITY.md
CHANGELOG.md

docs/
  README.md
  integrations/
    cursor.md
    claude-desktop.md
    hermes.md
    openwebui.md
    librechat.md
    openclaw.md
    mcp-reference.md
  guides/
    ingestion.md
    memory.md
    connectors.md
    agents-and-workspaces.md
  reference/
    api-rest.md
    api-openai-compat.md
    configuration.md
    architecture.md
  product/
    open-core-boundaries.md
    legacy.md
```

Минимальное содержание:

- `README.md`: основная информация о продукте остается: pitch, use cases, логическое разделение компонентов, surfaces API/MCP/OAI/OpenWebUI, open-core boundary на уровне ссылки. Текущий раздел установки нужно заменить на сокращенный install flow из `manual.md`: prerequisites, env setup, запуск сервисов, health check, первый ingestion/query, следующий шаг к агентскому подключению. README должен ссылаться на полный `manual.md`, подробный `install.md` для ошибок/развертывания и `connecting_to_agent.md` для MCP-подключения агента.
- `manual.md`: основной последовательный сценарий установки. Должен отвечать на вопрос "что делать по шагам": prerequisites, clone/download, env setup, запуск Core services, проверка health, загрузка первого документа/коннектора, первый search/chat запрос, следующий шаг к агентскому подключению.
- `install.md`: подробный справочник по развертыванию: manual install, scripted install, Docker Compose profiles, env vars, ports, health checks, database services, SPLADE, embedding proxy, freshness worker, metatron-api, OpenWebUI, production hardening, troubleshooting. Если в README/manual возникают ошибки, пользователь должен идти сюда.
- Старые `INSTALL.md` и `docs/INSTALL.md` должны быть удалены, переименованы или сведены в новый `install.md`; не оставлять два конкурирующих install-файла.
- `connecting_to_agent.md`: инструкция, что нужно передать приложенный prompt агенту/LLM. Prompt из `c:\Users\vasne\Downloads\prompt.txt` используется как источник, но перед публикацией его нужно привести к публичной форме: убрать Hermes-only формулировки из общего текста, убрать упоминание commercial-version workspaces, явно перечислить параметры `METATRON_URL`, `METATRON_MCP_API_KEY`, `AGENT_UUID`, `DEFAULT_WORKSPACE_ID`, описать headers `Authorization: Bearer ...` и `X-Agent-Id`, verification через `metatron_status` и memory tools.
- `docs/integrations/*.md`: конкретные инструкции для Cursor, Claude Desktop, Hermes, OpenWebUI, LibreChat, OpenClaw.
- `docs/guides/ingestion.md`: REST upload, connector sync, MCP `metatron_store`, supported file formats; без небезопасного server-local path endpoint.
- `docs/product/open-core-boundaries.md`: Core содержит 4 DB stack, SPLADE, embedding proxy, freshness worker, metatron-api, memory/RAG/MCP/OAI/REST surfaces, UI-KB reference; UI-CC/Control Center описан как отдельный коммерческий продукт вне этого repo.
- `docs/product/legacy.md`: публичная карта legacy/deprecated поверхностей, которые пока остаются ради совместимости: legacy channels, built-in chat route, skills stubs, benchmarker/dev-eval, Memgraph env aliases, compatibility shims. В файле должны быть статус, причина сохранения, рекомендуемая замена, planned removal/extraction path. Не включать Jira IDs, внутренние rollout notes, Agent Teams, private repo/process details.

## Verification

- Запустить repo-wide scans: `rg` по `MTRNIX-`, `atlassian.net`, `Control Center`, `UI-CC`, `metatron_enterprise`, `.claude`, `drp-m.mtrnix.com`, `change-me-in-production`, `chmod 777`, live-token patterns.
- Запустить test/lint/typecheck после удаления кода: `make lint`, `make typecheck`, `make test`.
- Запустить doc link check или минимальный `rg` на битые ссылки: `docs/adr`, `docs/superpowers`, deleted `examples/`, private install URLs, старые ссылки на `INSTALL.md` / `docs/INSTALL.md`, если canonical файл стал `install.md`.
- Перед публикацией прогнать secret scanner по full history, не только рабочему дереву.