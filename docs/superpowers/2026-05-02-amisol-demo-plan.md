# Amisol Demo Plan — Auto-generated User Guide + Admin Guide from Jira / Confluence / Bitbucket

**Date:** 2026-05-02
**Author:** plan compiled by assistant from Confluence page `MTRNIX/23756802` ("Client Case: Automated User Guide + Admin Guide from Jira and Confluence")
**Status:** working document for demo prep (synthetic data first, NDA later)
**Audience:** MTRNIX team (Ariel, David, Konstantin); private notes — not yet shared with the client

---

## 0. TL;DR

- Клиент Amisol (Michael Fiterman) хочет автоматически наполнять **существующий скелет** User Guide + Admin Guide из Jira (тысячи тикетов) + Confluence (~100 страниц) + Bitbucket. Сегодня всё руками: keyword-search → copy-paste → LLM prompt.
- Их вопрос: ок ли «RAG-per-feature»? Наш ответ: **направление верное, но архитектура должна быть RAG-per-section + hybrid retrieval (вектор + граф + метаданные + temporal) + section-level generation с цитатами**. Это ровно то, что Metatron уже делает.
- Прямого доступа к их данным **не будет** (NDA, German enterprise compliance, корпоративный лаптоп). Поэтому демо строится на **синтетическом датасете**, структурно повторяющем их мир.
- Демо длится 15–20 минут. Снять надо одну User Guide страницу + одну Admin Guide страницу + показать staleness/conflict/missing-info флаги + переиспользование того же KB на втором use case (marketing copy или compliance answer).
- Этот документ содержит:
  1. полную спецификацию синтетического датасета,
  2. файловые форматы под Jira / Confluence / Bitbucket / skeleton,
  3. **LLM-промпты для офлайн-генерации** маленькими моделями на локальном лаптопе,
  4. два пути загрузки (через настоящий Atlassian Cloud sandbox **или** напрямую в Metatron, если интернета нет),
  5. поминутный demo-script,
  6. дизайн ответа агента-документатора (схема, цитаты, флаги),
  7. как тот же KB подключается к другим агентам (PR-review, scrum, compliance, marketing) поверх Hermes / Claude Desktop / OAI-clients.

---

## 1. Source recap (что в Confluence-статье)

Полный текст в `MTRNIX/23756802`. Ключевое для демо:

- **Клиент:** Amisol; контакт — Michael Fiterman, R&D lead.
- **MTRNIX side:** Ariel Tov Ben, David Oren.
- **Источники у клиента:** Jira (epics / stories / requirements / defects, тысячи штук), Confluence (~100 страниц), Bitbucket (структура репозиториев + README), частичные существующие доки и **готовый скелет** обоих гайдов.
- **Среда:** German enterprise, compliance-heavy, скорее всего ограничены Azure-hosted OpenAI / Codex; self-hosted дружелюбно.
- **Их более широкий план AI:** PR-review, QA-помощник, генерация тест-кейсов, документация, маркетинг/sales/legal, customer-facing chatbot, compliance-questionnaire automation. То есть demo — это вход в платформу, а не одноразовый PoC.
- **Наша рекомендация (резюме):** RAG-per-document-section + hybrid retrieval + obligatory citations + conflict/staleness flags + SME-review loop + eval harness с golden questions.
- **Pitfalls статьи:** Jira defects описывают сломанное, а не ожидаемое поведение; старый Confluence vs новые Jira требования; vector search ловит «семантически похоже, но не тот продукт»; per-feature prompt быстро становится дорого; permissions должны быть сохранены.

---

## 2. Demo objective

**Одна история за 15–20 минут:**

> «Вот ваши Jira-тикеты и Confluence-страницы. За один прогон Metatron вытаскивает релевантный контекст по правильному feature, агент генерирует страницу User Guide и страницу Admin Guide ровно по вашему скелету, каждый абзац подписан источниками. Где источники конфликтуют — мы это явно показываем, не угадываем. Тот же индекс прямо сейчас отвечает на маркетинговый вопрос и на пункт compliance-опросника — без переиндексации.»

**Минимально достаточно показать:**
1. Источники → ingestion → Hybrid KB.
2. «Сгенерируй User Guide page для feature X» → секции → цитаты.
3. «Сгенерируй Admin Guide page для feature X» → разделы про конфигурацию / роли / troubleshooting → цитаты.
4. **Один намеренный конфликт** между Jira и Confluence — агент его флагает, не сглаживает.
5. **Один staleness-кейс** — старая страница помечена как superseded.
6. **Второй use case на том же индексе** — например «дай ответ маркетингу про feature X» или «ответь на compliance-вопрос Q».
7. (опц.) Подключение к внешнему агенту через MCP (Claude Desktop / Hermes / Cursor) — показать AI-agnostic claim руками.

**НЕ нужно показывать:** сам процесс ingestion от Atlassian-API в реальном времени, тонкости Neo4j, eval harness в цифрах. Это для follow-up.

---

## 3. Demo architecture (как стоит на сцене)

```
┌────────────────────────────────────────────────────────────┐
│  Synthetic source systems                                  │
│                                                            │
│  Jira sandbox (or files) ── Confluence sandbox (or files)  │
│            │                          │                    │
│            └──────────┬───────────────┘                    │
│                       │  Bitbucket READMEs (files)         │
└───────────────────────┼────────────────────────────────────┘
                        ▼
                 Metatron ingestion
                 (connectors → PG → Qdrant + Neo4j)
                        │
                        ▼
            ┌──────────────────────────┐
            │   Hybrid KB              │
            │   • vector (768d, SPLADE)│
            │   • graph (Doc/Chunk/Ent)│
            │   • metadata + temporal  │
            └────────────┬─────────────┘
                         │
        ┌────────────────┼─────────────────────────────┐
        ▼                ▼                             ▼
   MCP server     OAI-compat /v1/chat       REST /api/v1/search
   (Hermes,       (LibreChat, OpenWebUI,    (custom agents)
    Cursor,        any OAI client)
    Claude
    Desktop)
        │                │                             │
        └─────────┬──────┴─────────────────────────────┘
                  ▼
        Doc-Generator agent
        ┌─────────────────────────┐
        │ 1. Read skeleton        │
        │ 2. For each section:    │
        │    • build retrieval Q  │
        │    • call hybrid_search │
        │    • LLM-fill section   │
        │    • attach citations   │
        │    • flag uncertainty   │
        │ 3. Compose page         │
        │ 4. Run quality checks   │
        └────────────┬────────────┘
                     ▼
        Generated guide page (JSON + Markdown)
                     │
                     ▼
                SME review
```

Идея демо: один «оркестратор» — Doc-Generator agent — может жить вне Metatron (Hermes / OpenAI / Claude Desktop). Метатрон отвечает только за поиск и контекст. Это и есть AI-agnostic positioning.

---

## 4. Synthetic dataset specification

### 4.1 Fictional product

- **Name:** `Amisol DataPlatform Demo` (заменимо). Везде в демо префикс ключей и спейсов — `DPLAT`.
- **Что делает:** B2B enterprise data integration + compliance vault. Тип продукта подобран близко к реальной нише Amisol — данные + comply.
- **Domain language (важно для retrieval-quality):** "connector", "data source", "PII", "retention", "audit log", "tenant", "workspace admin", "compliance officer".

### 4.2 Modules / features / roles

| ID | Type | Name | Why included |
|----|------|------|--------------|
| MOD-A | module | Connector Framework | пример "user-facing config + admin-facing limits" |
| MOD-B | module | Compliance Vault | пример "regulated data, role-gated config" |
| F-A1 | feature | Salesforce Connector | большой connector с UI потоком |
| F-A2 | feature | SAP S/4HANA Connector | second connector, чтобы было что путать векторному поиску |
| F-A3 | feature | Connector Health Monitor | админская фича, без user-facing UI |
| F-B1 | feature | PII Auto-Tagging | user-видит результат, админ настраивает классификатор |
| F-B2 | feature | Audit Log Export | чисто админская + compliance-officer-facing |
| ROLE-EU | role | End User | базовое использование |
| ROLE-WA | role | Workspace Admin | конфигурация, лимиты, ключи |
| ROLE-CO | role | Compliance Officer | политика, экспорты, retention |

### 4.3 Volume targets

| Artifact | Count | Notes |
|----------|------:|-------|
| Jira Epics | **5** | по одному на feature |
| Jira Stories | **15** | 3 на feature; user-stories с acceptance criteria |
| Jira Requirements | **10** | non-functional / business rules |
| Jira Defects | **8** | минимум **2 содержат намеренный конфликт** с Confluence |
| Confluence pages | **10** | разные типы (см. 4.4) |
| Bitbucket README files | **3** | по одному на сервис-репозиторий |
| Doc skeletons | **2** | User Guide + Admin Guide YAML TOC |

Итого ~40 артефактов. Достаточно, чтобы retrieval имел что путать, и достаточно мало, чтобы можно было руками проверить, что демо честное.

### 4.4 Confluence page mix (10 страниц)

| # | Type | Slug | Назначение в демо |
|---|------|------|-------------------|
| 1 | Product Overview | `01-product-overview` | top-level |
| 2 | Module Brief | `02-connector-framework-overview` | для F-A1/A2/A3 родитель |
| 3 | Module Brief | `03-compliance-vault-overview` | для F-B1/B2 родитель |
| 4 | Feature Business Rules | `04-salesforce-connector-business-rules` | главный «бизнес-источник» для F-A1 |
| 5 | Feature Business Rules | `05-pii-auto-tagging-policy` | главный для F-B1 |
| 6 | API Spec | `06-connector-config-api` | техническая страница, для Admin Guide |
| 7 | Troubleshooting | `07-salesforce-connector-troubleshooting` | для Admin Guide / known errors |
| 8 | Release Notes | `08-release-notes-v2-3` | свежее, источник «правды о текущем поведении» |
| 9 | **Legacy / superseded** | `09-pii-tagging-initial-design-LEGACY` | помечен старой датой + label `superseded`; намеренно противоречит F-B1 |
| 10 | Partial existing user guide | `10-getting-started-DRAFT` | то, что у клиента уже есть в скелете |

### 4.5 Намеренные «качественные сигналы» (без них демо не честное)

| # | Signal | Конкретно где | Что должен показать агент |
|---|--------|---------------|----------------------------|
| C1 | **Conflict** | Defect `DPLAT-DEF-04` говорит: default retention = 90d. Confluence `05-pii-auto-tagging-policy` говорит: 30d. Story `DPLAT-006` (Recent) — 60d. | секция «Retention» помечена `conflicting_sources`, рядом 3 цитаты, явный «нужен SME» |
| C2 | **Staleness** | `09-pii-tagging-initial-design-LEGACY` (updated 2024-04, label `superseded`) vs Story `DPLAT-005` (updated 2026-04) | Metatron отдаёт recent с recency-boost, legacy либо отфильтрован, либо помечен `stale` |
| C3 | **Missing info** | Никто не описывает retention для `Audit Log Export` | секция отрисована как `unknown`, агент **не выдумывает**, явно пишет "no source" |
| C4 | **Cross-source linking** | Story `DPLAT-002` ссылается на Confluence `04-...-business-rules`; Defect `DPLAT-DEF-02` тоже | Graph traversal: один запрос — три источника, видны связи |
| C5 | **Permission split** | Configuration of Audit Export — только Admin Guide. Setup Salesforce Connector — User Guide. | две сгенерированные страницы **разные**, хотя источники пересекаются |
| C6 | **Defect ≠ behavior** | `DPLAT-DEF-07` описывает баг "PII tagging skips emails in CSV". | агент не пишет в User Guide «емейлы в CSV не теггируются» — он пишет «известное ограничение, см. troubleshooting» |

Эти сигналы стоит готовить **сразу при генерации**, а не чинить пост-фактум.

---

## 5. File layout (что лежит на лаптопе)

```
demo-data/
├── README.md                        # как пользоваться — для самого Konstantin
├── jira/                            # один файл на тикет
│   ├── DPLAT-EPIC-01.json           # Connector Framework epic
│   ├── DPLAT-EPIC-02.json
│   ├── DPLAT-EPIC-03.json
│   ├── DPLAT-EPIC-04.json
│   ├── DPLAT-EPIC-05.json
│   ├── DPLAT-001.json … DPLAT-015.json   # stories
│   ├── DPLAT-REQ-01.json … DPLAT-REQ-10.json
│   └── DPLAT-DEF-01.json … DPLAT-DEF-08.json
├── confluence/
│   └── DPLAT/
│       ├── 01-product-overview.md
│       ├── 02-connector-framework-overview.md
│       ├── 03-compliance-vault-overview.md
│       ├── 04-salesforce-connector-business-rules.md
│       ├── 05-pii-auto-tagging-policy.md
│       ├── 06-connector-config-api.md
│       ├── 07-salesforce-connector-troubleshooting.md
│       ├── 08-release-notes-v2-3.md
│       ├── 09-pii-tagging-initial-design-LEGACY.md
│       └── 10-getting-started-DRAFT.md
├── bitbucket/
│   ├── connector-framework/README.md
│   ├── compliance-vault/README.md
│   └── shared-libs/README.md
├── skeletons/
│   ├── user-guide.yaml
│   └── admin-guide.yaml
└── seed/
    ├── seed_jira.py                 # online: pushes JSON → Jira via REST
    ├── seed_confluence.py           # online: pushes md → Confluence via REST (md→storage)
    └── seed_metatron_direct.py      # offline-friendly: bypasses Atlassian, ingests via Metatron API
```

Один файл = один артефакт. Это специально:
- генерация одного тикета — короткий промпт, маленькая модель не сваливается;
- легко резюмировать после прерывания (`for f in jira/*.json; do …`);
- легко проверить руками или git-diff'нуть отдельный артефакт.

---

## 6. File format specs

### 6.1 Jira issue — `jira/<KEY>.json`

Внутренний контейнерный формат (не Atlassian REST напрямую — он избыточный и хрупкий). Loader-скрипт переведёт его в нужный для Atlassian REST `POST /rest/api/3/issue`.

```json
{
  "key": "DPLAT-002",
  "issuetype": "Story",
  "project_key": "DPLAT",
  "epic_link": "DPLAT-EPIC-01",
  "summary": "Salesforce connector — initial setup wizard",
  "description_md": "As a workspace admin, I want to set up a Salesforce connector via a guided wizard so that I can ingest Account/Opportunity records into the platform.\n\n**Background:** ...\n\n**Acceptance criteria:**\n- AC1: ...\n- AC2: ...",
  "priority": "Medium",
  "status": "Done",
  "labels": ["module:connector-framework", "feature:F-A1", "role:workspace-admin", "user-facing"],
  "components": ["Connector Framework"],
  "fix_versions": ["v2.3"],
  "affects_versions": [],
  "reporter": "michael.fiterman@amisol-demo.example",
  "assignee": "dev1@amisol-demo.example",
  "created": "2026-02-10T09:00:00Z",
  "updated": "2026-04-12T10:30:00Z",
  "resolved": "2026-04-12T10:30:00Z",
  "linked_issues": [
    {"type": "blocks", "key": "DPLAT-003"},
    {"type": "relates", "key": "DPLAT-DEF-02"}
  ],
  "linked_confluence": [
    {"space": "DPLAT", "slug": "04-salesforce-connector-business-rules"}
  ],
  "comments": [
    {"author": "qa1@amisol-demo.example", "created": "2026-03-01T12:00:00Z",
     "body_md": "Tested with sandbox org, OAuth flow works. Token expiry: 2h."}
  ]
}
```

Required: `key`, `issuetype`, `project_key`, `summary`, `description_md`, `status`, `created`, `updated`, `labels`, `reporter`.

`issuetype` ∈ `{Epic, Story, Task, Requirement, Bug}`. Bug = "Defect" в client's Jira; маппить при загрузке если понадобится.

`labels` — основной носитель **structured metadata** для retrieval. Соглашения:
- `module:<id>` — `module:connector-framework` / `module:compliance-vault`
- `feature:<id>` — `feature:F-A1` … `feature:F-B2`
- `role:<id>` — `role:end-user` / `role:workspace-admin` / `role:compliance-officer`
- `surface:user-guide` / `surface:admin-guide` — какую часть гайда заполняет (опционально, помогает retrieval)
- `behavior:intended` / `behavior:defect` — критично! defects получают `behavior:defect`, чтобы агент не путал.

### 6.2 Confluence page — `confluence/<SPACE>/<NN>-<slug>.md`

Markdown с YAML frontmatter:

```markdown
---
space: DPLAT
slug: 04-salesforce-connector-business-rules
title: "Salesforce Connector — Business Rules"
parent_slug: 02-connector-framework-overview
labels:
  - module:connector-framework
  - feature:F-A1
  - doc-type:business-rules
  - source-of-truth
author: ariel@mtrnix.example
created: "2026-02-15T08:00:00Z"
updated: "2026-04-18T14:00:00Z"
version: 7
status: current        # current | draft | superseded
linked_jira:
  - DPLAT-001
  - DPLAT-002
  - DPLAT-REQ-03
---

# Salesforce Connector — Business Rules

## Purpose
The Salesforce connector ingests Account, Opportunity, and Contact records into a workspace …

## Object scope
- Account: …
- Opportunity: …

## Sync frequency
…

## Authentication
We use OAuth 2.0 against the customer's Salesforce org. The default token TTL is 2 hours …

## Error handling
…

## Retention of cached data
The connector keeps a local copy of pulled records for **30 days** by default
(see *PII Auto-Tagging Policy* page for the platform-wide retention contract). [INTENTIONAL CONFLICT C1]
```

`status: superseded` + `labels: [..., superseded]` — для legacy-страницы 09. `version` важно — Metatron freshness-pipeline им пользуется.

### 6.3 Bitbucket README — `bitbucket/<repo>/README.md`

Простой Markdown без frontmatter. Цель — добавить третий источник, чтобы графовое связывание было нетривиальным. README-и должны:
- упоминать названия модулей/фичей словами,
- содержать ссылки вида `JIRA: DPLAT-001`, `Confluence: DPLAT/04-...-business-rules`,
- иметь раздел "Configuration" с env-переменными (Admin Guide любит такое).

### 6.4 Skeleton — `skeletons/user-guide.yaml` / `admin-guide.yaml`

```yaml
guide: user-guide
audience: [end-user, workspace-admin]
sections:
  - id: 1.0
    title: "Introduction"
    intent: "Brief product positioning. 3 paragraphs."
    retrieval:
      questions:
        - "What does the platform do at a high level?"
        - "Who is the primary user?"
      filters:
        labels: ["doc-type:overview"]

  - id: 2.0
    title: "Getting started"
    children:
      - id: 2.1
        title: "Setting up a Salesforce connector"
        feature: F-A1
        retrieval:
          questions:
            - "What is the user-facing setup flow for the Salesforce connector?"
            - "What permissions does the user need?"
            - "What are common errors during setup and how does the user resolve them?"
          filters:
            labels_any: ["feature:F-A1"]
            labels_none: ["behavior:defect"]
            roles: ["end-user", "workspace-admin"]
        sections_required:
          - "Prerequisites"
          - "Steps"
          - "Verification"
          - "Troubleshooting (common)"

      - id: 2.2
        title: "Setting up a SAP S/4 connector"
        feature: F-A2
        # ...

  - id: 3.0
    title: "Working with PII tagging"
    feature: F-B1
    # ...
```

Принцип: **каждая секция декларативно описывает свой retrieval intent** — какие вопросы задать KB, по каким лейблам фильтровать, какие подсекции обязательны. Это и есть «RAG-per-section», который мы продаём клиенту вместо «RAG-per-feature».

Admin Guide — те же features, но `audience: [workspace-admin, compliance-officer]`, и в `sections_required` появляются "Configuration", "Limits", "Audit", "Permissions matrix", "Backup & recovery".

---

## 7. Offline LLM generation playbook

### 7.1 Local runtime — oMLX на Mac

**Стек на машине Konstantin'а:** `omlx` (`/opt/homebrew/bin/omlx`) — production-ready OpenAI-совместимый сервер для Apple Silicon на базе MLX. Конфиг в `~/.omlx/settings.json`. Модели — симлинки в `~/.omlx/models/` на скачанное в `~/.cache/huggingface/`.

**Запуск:** сервер слушает `127.0.0.1:8090/v1/...` (порт из `settings.json`). Команда:

```bash
omlx serve --port 8090     # либо: omlx serve qwen36-a3b --port 8090 (с предзагрузкой)
```

Сам по себе `omlx serve` поднимает мульти-модельный сервер: модели загружаются в память лениво по первому запросу с конкретным `model: "<alias>"`. CORS открыт для всех origin'ов, `max_concurrent_requests: 8`, `max_context_window: 131072`. Если в конфиге появится непустой `auth.api_key` — добавлять `Authorization: Bearer <key>` к запросам; пока `null` — без хедера.

#### 7.1.1 Доступные модели (фактические symlinks на машине)

| alias в API | upstream | RAM | Что это |
|---|---|---|---|
| `qwen36-a3b` | `unsloth/Qwen3.6-35B-A3B-MLX-**8bit**` | ~35GB | MoE: 35B total / 3B active. **8-bit** квант — качество ощутимо выше 4-bit; основная рабочая лошадка |
| `qwen-opus` | `mlx-community/Qwen3.5-27B-Claude-4.6-Opus-Distilled-MLX-4bit` | ~16GB | плотная 27B, дистиллирована из Claude Opus 4.6 — стиль и instruction-following близки к Claude; самая «литературная» из трёх |
| `gemma-4` | `mlx-community/gemma-4-26b-a4b-it-4bit` | ~14GB | MoE 26B / 4B active, 4-bit — самая быстрая, для коротких/мусорных задач |

#### 7.1.2 Распределение моделей по режимам генерации

Откалибровано замерами на этой машине (2026-05-02): `qwen36-a3b` и `qwen-opus` оба держат `response_format: json_schema`, но **`qwen36-a3b` — reasoning-модель** и сжигает ~800–1000 completion-tokens на CoT в каждом запросе (CoT уходит в `reasoning_content`, не в `content`). `qwen-opus` справляется с теми же задачами в **~3× меньше токенов** при сопоставимой schema-валидности. Поэтому `qwen-opus` — главная рабочая лошадка; `qwen36-a3b` зарезервирован для задач, где reasoning реально окупается.

| Артефакт | Главная модель | temperature | max_tokens | json_mode | Почему |
|---|---|---|---|---|---|
| **Jira Epic / Story / Task** | `qwen-opus` | `0.4` | `2000` | `schema` | держит схему, экономит токены, без CoT-оверхеда |
| **Jira Defect** (repro + AC) | `qwen36-a3b` | `0.4` | `4500` | `schema` | здесь reasoning реально помогает: связные repro steps и AC |
| **Jira Requirement** | `qwen-opus` | `0.4` | `2500` | `schema` | non-functional пункты, схема та же |
| **Confluence Markdown** + frontmatter | `qwen-opus` | `0.7` | `3500` | `none` | Claude-distilled даёт самую живую прозу + держит YAML frontmatter |
| **YAML skeleton** | `gemma-4` | `0.3` | `2500` | `none` | дёшево и быстро; YAML простой, схема не нужна |
| **Bitbucket README** | `qwen-opus` | `0.6` | `1500` | `none` | свободный жанр, но хочется складный английский |

Это оставляет в RAM **одну модель — `qwen-opus` (~16GB)** на 90% работы, что комфортно даже на M-Pro 32GB. `qwen36-a3b` подгружается только для 8 defect-генераций; `gemma-4` — для двух YAML.

#### 7.1.3 Schema-constrained generation в oMLX

**Подтверждено замерами:** oMLX 1.0 на этой машине поддерживает все три уровня — `json_schema`, `json_object`, plain. Дефолт для Jira-артефактов — `schema`.

1. **`response_format: {"type": "json_schema", "json_schema": {...}}`** — основной режим для Jira: грамматика на токенизатор, валидный JSON по схеме гарантирован. Полностью работает на `qwen-opus` и `qwen36-a3b`.
2. **`response_format: {"type": "json_object"}`** — fallback: «выдай любой валидный JSON». Используется если schema-уровень почему-то возвращает HTTP-ошибку.
3. **plain text + post-validation** — финальный fallback для Markdown / YAML.

`scripts/gen.py` (§7.1.6) делает каскадный фоллбэк автоматически: если `schema` отдал HTTP-ошибку — пробует `object`, потом plain. Поведение логируется в stderr.

**Reasoning models (`qwen36-a3b`):** ответ возвращается как `{message: {content: "...JSON...", reasoning_content: "...CoT..."}}`. Парсить нужно `content`. `reasoning_content` можно игнорировать (или логировать для дебага). Бюджет `max_tokens` должен покрывать **CoT + answer** — для qwen36-a3b закладывайте ≥4000.

#### 7.1.4 Пример: одна Jira Story с json_schema

`prompts/schemas/jira_issue.schema.json` (JSON Schema, общая для Epic/Story/Task/Bug):

```json
{
  "name": "JiraIssue",
  "schema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["key", "issuetype", "project_key", "summary", "description_md",
                 "priority", "status", "labels", "components", "fix_versions",
                 "affects_versions", "reporter", "assignee", "created", "updated",
                 "linked_issues", "linked_confluence", "comments"],
    "properties": {
      "key":        {"type": "string", "pattern": "^DPLAT-(EPIC-|REQ-|DEF-)?[0-9]+$"},
      "issuetype":  {"type": "string", "enum": ["Epic", "Story", "Task", "Bug"]},
      "project_key":{"type": "string", "const": "DPLAT"},
      "epic_link":  {"type": ["string", "null"]},
      "summary":    {"type": "string", "minLength": 5, "maxLength": 200},
      "description_md": {"type": "string", "minLength": 50},
      "priority":   {"type": "string", "enum": ["High", "Medium", "Low"]},
      "status":     {"type": "string", "enum": ["To Do", "In Progress", "Done", "Open"]},
      "labels":     {"type": "array",  "items": {"type": "string"}, "minItems": 2},
      "components": {"type": "array",  "items": {"type": "string"}},
      "fix_versions":   {"type": "array", "items": {"type": "string"}},
      "affects_versions":{"type": "array", "items": {"type": "string"}},
      "reporter":   {"type": "string", "format": "email"},
      "assignee":   {"type": "string", "format": "email"},
      "created":    {"type": "string", "format": "date-time"},
      "updated":    {"type": "string", "format": "date-time"},
      "resolved":   {"type": ["string", "null"], "format": "date-time"},
      "linked_issues": {"type": "array", "items": {
        "type": "object", "required": ["type", "key"],
        "properties": {"type": {"type": "string"}, "key": {"type": "string"}}}},
      "linked_confluence": {"type": "array", "items": {
        "type": "object", "required": ["space", "slug"],
        "properties": {"space": {"type": "string"}, "slug": {"type": "string"}}}},
      "comments": {"type": "array", "items": {
        "type": "object", "required": ["author", "created", "body_md"],
        "properties": {
          "author":  {"type": "string", "format": "email"},
          "created": {"type": "string", "format": "date-time"},
          "body_md": {"type": "string"}}}}
    }
  }
}
```

Запрос (вручную через `jq` — heredoc подставлять неудобно, JSON-обёртка собирается из частей):

```bash
jq -n \
  --slurpfile schema  prompts/schemas/jira_issue.schema.json \
  --rawfile  systxt   prompts/system/jira_story.system.txt \
  --rawfile  usertxt  prompts/payloads/DPLAT-002.user.txt \
  '{
    model: "qwen36-a3b",
    temperature: 0.4,
    max_tokens: 2000,
    response_format: { type: "json_schema", json_schema: $schema[0] },
    messages: [
      { role: "system", content: $systxt },
      { role: "user",   content: $usertxt }
    ]
  }' | curl -s http://127.0.0.1:8090/v1/chat/completions \
         -H "Content-Type: application/json" \
         -d @- \
       | jq -r '.choices[0].message.content' \
       > demo-data/jira/DPLAT-002.json
```

Если oMLX в данной сборке не понимает `json_schema`, заменить `response_format` на `{type: "json_object"}` и вынести схему в system-prompt текстом — см. §7.1.3 уровень 2.

На практике — пользоваться `scripts/gen.py` (§7.1.6), он сам подбирает уровень.

#### 7.1.5 Пример: одна Confluence-страница (без schema)

```bash
curl -s http://127.0.0.1:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-opus",
    "temperature": 0.7,
    "max_tokens": 3000,
    "messages": [
      {"role": "system", "content": "<<system prompt §7.3.5>>"},
      {"role": "user",   "content": "<<user prompt for slug 04>>"}
    ]
  }' | jq -r '.choices[0].message.content' \
     > demo-data/confluence/DPLAT/04-salesforce-connector-business-rules.md
```

#### 7.1.6 Python-обёртка для batch-генерации (oMLX)

Один файл, идемпотентный, с авто-фоллбэком уровней строгости. Положить в `scripts/gen.py`:

```python
#!/usr/bin/env python3
"""
Generate one synthetic artifact via oMLX (OpenAI-compatible) server.

Layout convention:
  prompts/system/<kind>.system.txt          system prompt (per artifact kind)
  prompts/schemas/<kind>.schema.json        OPTIONAL — JSON Schema for json_schema mode
  prompts/payloads/<id>.user.txt            user prompt (one per artifact)
  prompts/payloads/<id>.meta.json           per-artifact config (see below)

meta.json:
  {
    "kind":      "jira" | "confluence" | "skeleton" | "readme",
    "out":       "demo-data/jira/DPLAT-002.json",
    "model":     "qwen36-a3b" | "qwen-opus" | "gemma-4",   # optional, default by kind
    "json_mode": "schema" | "object" | "none"              # optional, default by kind
  }

Usage:
  python scripts/gen.py prompts/payloads/DPLAT-002          # one artifact
  python scripts/gen.py prompts/payloads/                   # everything
  OMLX_BASE=http://127.0.0.1:8090 python scripts/gen.py …    # override endpoint
"""
from __future__ import annotations
import json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

BASE      = os.environ.get("OMLX_BASE",   "http://127.0.0.1:8090")
API_KEY   = os.environ.get("OMLX_API_KEY", "")          # empty = no Authorization header
DEBUG_CoT = os.environ.get("OMLX_LOG_REASONING", "") not in ("", "0", "false")
ENDPOINT  = f"{BASE}/v1/chat/completions"

# Per-kind defaults: (model alias, temperature, max_tokens, json_mode)
# Calibrated 2026-05-02: qwen-opus is non-CoT-overhead; qwen36-a3b reasoning-burns ~1000 tok.
# Reserved qwen36-a3b only for kinds where reasoning genuinely improves output.
KIND_DEFAULTS = {
    "jira":        ("qwen-opus",  0.4, 2000, "schema"),   # Epic / Story / Task
    "jira_defect": ("qwen36-a3b", 0.4, 4500, "schema"),   # repro + AC benefit from CoT
    "jira_req":    ("qwen-opus",  0.4, 2500, "schema"),
    "confluence":  ("qwen-opus",  0.7, 3500, "none"),
    "skeleton":    ("gemma-4",    0.3, 2500, "none"),
    "readme":      ("qwen-opus",  0.6, 1500, "none"),
}

def post(payload: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode(), headers=headers,
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode())

def call_once(messages, model, temperature, max_tokens, json_mode, schema):
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "messages":    messages,
    }
    if   json_mode == "schema" and schema is not None:
        payload["response_format"] = {"type": "json_schema", "json_schema": schema}
    elif json_mode == "object":
        payload["response_format"] = {"type": "json_object"}
    body = post(payload)
    choice = body["choices"][0]
    msg = choice["message"]
    finish = choice.get("finish_reason")
    if finish == "length":
        raise RuntimeError(f"truncated (finish_reason=length, model={model}, "
                           f"completion_tokens={body.get('usage',{}).get('completion_tokens')}). "
                           f"Increase max_tokens.")
    if DEBUG_CoT and msg.get("reasoning_content"):
        rc = msg["reasoning_content"]
        print(f"  CoT [{model}] {len(rc)} chars: {rc[:160]!r}…", file=sys.stderr)
    # oMLX places the actual answer in `content`; reasoning models also fill `reasoning_content`.
    return msg["content"] or ""

def call_with_fallback(messages, model, temperature, max_tokens, json_mode, schema):
    """Try requested json_mode; if oMLX rejects it, fall back step by step."""
    levels = {"schema": ["schema", "object", "none"],
              "object": ["object", "none"],
              "none":   ["none"]}.get(json_mode, ["none"])
    last_err = None
    for level in levels:
        try:
            text = call_once(messages, model, temperature, max_tokens, level, schema)
            if level != json_mode:
                print(f"  note: server rejected json_mode={json_mode}, used {level}", file=sys.stderr)
            return text, level
        except urllib.error.HTTPError as e:
            last_err = f"{e.code} {e.reason}: {e.read()[:300].decode(errors='replace')}"
            continue
    raise RuntimeError(f"all json_mode levels failed: {last_err}")

def generate(stem: Path) -> None:
    meta = json.loads(stem.with_suffix(".meta.json").read_text())
    kind = meta["kind"]
    out  = Path(meta["out"])
    if out.exists():
        print(f"skip   {out} (exists)")
        return

    if kind not in KIND_DEFAULTS:
        raise ValueError(f"unknown kind={kind!r}; expected one of {list(KIND_DEFAULTS)}")
    default_model, default_temp, default_max, default_jm = KIND_DEFAULTS[kind]
    model     = meta.get("model",       default_model)
    json_mode = meta.get("json_mode",   default_jm)
    temp      = meta.get("temperature", default_temp)
    max_toks  = meta.get("max_tokens",  default_max)

    # System prompt: try exact kind, fall back to base kind before "_"
    # e.g. "jira_defect" → "prompts/system/jira_defect.system.txt"; if absent, "jira.system.txt".
    sys_paths = [Path(f"prompts/system/{kind}.system.txt")]
    if "_" in kind:
        sys_paths.append(Path(f"prompts/system/{kind.split('_')[0]}.system.txt"))
    system_prompt = next((p.read_text() for p in sys_paths if p.exists()), None)
    if system_prompt is None:
        raise FileNotFoundError(f"no system prompt for kind={kind!r}; tried {sys_paths}")

    user_prompt = stem.with_suffix(".user.txt").read_text()

    # Schema: same fallback rule
    sch_paths = [Path(f"prompts/schemas/{kind}.schema.json")]
    if "_" in kind:
        sch_paths.append(Path(f"prompts/schemas/{kind.split('_')[0]}.schema.json"))
    schema_path = next((p for p in sch_paths if p.exists()), None)
    schema = json.loads(schema_path.read_text()) if schema_path else None

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]

    t0 = time.time()
    text, used = call_with_fallback(messages, model, temp, max_toks, json_mode, schema)

    # Post-validate JSON if we expected JSON (any level) but server gave us something dirty.
    if json_mode in ("schema", "object"):
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"non-JSON response despite json_mode={json_mode} (used={used}): {e}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(f"wrote  {out}  [{model}/{used}]  {len(text)}b  {time.time()-t0:.1f}s")

def iter_stems(target: Path):
    if target.is_file() or target.with_suffix(".meta.json").exists():
        yield target
        return
    for meta in sorted(target.glob("*.meta.json")):
        yield meta.with_suffix("")  # strip .json → leaves .meta; strip again below
    # Need to strip both suffixes for stems like "DPLAT-002.meta.json"
def stem_of(meta_path: Path) -> Path:
    # "DPLAT-002.meta.json" → "DPLAT-002"
    return meta_path.with_suffix("").with_suffix("")

def main(argv: list[str]) -> int:
    target = Path(argv[1])
    if target.is_dir():
        metas = sorted(target.glob("*.meta.json"))
        if not metas:
            print(f"no *.meta.json files under {target}", file=sys.stderr)
            return 2
        for m in metas:
            try:
                generate(stem_of(m))
            except Exception as e:
                print(f"FAIL   {m}: {e}", file=sys.stderr)
    else:
        # accept either ".../DPLAT-002" or ".../DPLAT-002.meta.json"
        if target.suffixes[-2:] == [".meta", ".json"]:
            target = stem_of(target)
        generate(target)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

Запуск:

```bash
# 1. Поднять oMLX (один раз, в отдельном терминале)
omlx serve --port 8090

# 2. Sanity check
curl -s http://127.0.0.1:8090/v1/models | jq

# 3. Генерация
python scripts/gen.py prompts/payloads/                  # всё, что ещё не сгенерировано
python scripts/gen.py prompts/payloads/DPLAT-002         # один артефакт

# Если в settings.json появится непустой api_key:
OMLX_API_KEY=<key> python scripts/gen.py prompts/payloads/
```

Скрипт **идемпотентен** — пропускает существующие выходные файлы. Авто-фоллбэк уровней строгости: если oMLX вернул HTTP-ошибку на `json_schema` — пробует `json_object`, потом plain text. После любого JSON-режима делает `json.loads()` для пост-валидации; если ответ оказался не JSON — фейлится с понятной ошибкой, можно перезапустить.

#### 7.1.7 Hardware notes для твоей конфигурации

- `qwen36-a3b` (8-bit, ~35GB) — нужен M2/M3 Max 64GB или M3 Ultra. На 32GB не поедет — ставить вместо него 4-bit вариант (`mlx-community/Qwen3.6-35B-A3B-MLX-4bit`, ~20GB) и засимлинковать как новый алиас, например `qwen36-a3b-4bit`.
- `qwen-opus` (4-bit, ~16GB) — комфортно на 32GB.
- `gemma-4` (4-bit, ~14GB) — на любом современном M-Mac.
- **Параллельность.** oMLX держит несколько моделей одновременно (`max_concurrent_requests: 8` в `settings.json`), но память считается на сумму — если запустишь Jira-генерацию (`qwen36-a3b`) и Confluence-генерацию (`qwen-opus`) параллельно, нужно ~50GB свободной RAM. На лаптопе обычно проще делать **последовательно**: сначала все Jira (одна модель в памяти), потом все Confluence, потом остальное.
- **Тепло.** Длинная batch-генерация в дороге = throttling. Лучше зарядка + кафе, чем самолёт.

### 7.2 Generation order (важно — есть зависимости)

1. **Зафиксировать вручную (5 минут)** — `demo-data/SEEDS.md` с заранее выписанной таблицей: features, roles, ключи всех тикетов, slug'и страниц, какие artefacts участвуют в C1/C2/C3/C4/C5/C6. Без этого LLM начнёт расходиться.
2. Сгенерировать **Skeletons** (`user-guide.yaml`, `admin-guide.yaml`) — по одному промпту, см. §7.3.6.
3. Сгенерировать **Epics** (5) — каждый отдельным промптом, см. §7.3.1.
4. Сгенерировать **Stories** (15), каждая ссылается на epic — §7.3.2.
5. Сгенерировать **Requirements** (10) — §7.3.3.
6. Сгенерировать **Defects** (8) — §7.3.4. Обязательно вручную задать summary'ы для DEF-02 (linked C4), DEF-04 (conflict C1), DEF-07 (defect-not-behavior C6).
7. Сгенерировать **Confluence pages** (10) — §7.3.5. Страница 09 (legacy) генерируется отдельным промптом с явным указанием «opposite of current» по retention.
8. Сгенерировать **README** (3) — §7.3.7.
9. Прогнать **валидатор** (см. §7.4) — проверить, что все ссылки между файлами разрешаются, лейблы согласованы, все 6 quality signals (C1–C6) реально присутствуют.

### 7.3 Prompt library

Все промпты ниже самодостаточны (включают полную схему). Подразумеваются как `system` + `user` в API-вызове.

#### 7.3.1 Jira Epic (`prompts/jira_epic.md`)

```
SYSTEM:
You are a senior product manager generating a synthetic but realistic Jira Epic
for an internal demo of a B2B enterprise data integration platform called
"Amisol DataPlatform Demo" (key: DPLAT). Output must be a single JSON object
that exactly matches the schema below — no prose, no markdown fences.

Schema:
{
  "key": "DPLAT-EPIC-XX",
  "issuetype": "Epic",
  "project_key": "DPLAT",
  "epic_link": null,
  "summary": "<short title>",
  "description_md": "<3-6 paragraphs of product context, non-functional goals, scope, out-of-scope>",
  "priority": "High|Medium|Low",
  "status": "In Progress|Done",
  "labels": ["module:<id>", "feature:<id>", "behavior:intended"],
  "components": ["<module name>"],
  "fix_versions": ["v2.3"],
  "affects_versions": [],
  "reporter": "michael.fiterman@amisol-demo.example",
  "assignee": "michael.fiterman@amisol-demo.example",
  "created": "2026-01-XXTXX:XX:XXZ",
  "updated": "2026-04-XXTXX:XX:XXZ",
  "resolved": null,
  "linked_issues": [],
  "linked_confluence": [{"space": "DPLAT", "slug": "<corresponding overview slug>"}],
  "comments": []
}

Rules:
- Domain language is mandatory: "connector", "data source", "PII", "retention",
  "audit log", "tenant", "workspace admin", "compliance officer".
- description_md is in Markdown, with sections: Background, Goal, Scope, Out of scope, Success metrics.
- Don't invent features outside the SEEDS table provided in the user message.
- All dates are ISO-8601 UTC.

USER:
Generate the Epic with the following identity:
- key: DPLAT-EPIC-01
- title: "Salesforce Connector"
- module: MOD-A (Connector Framework)
- feature: F-A1 (Salesforce Connector)
- linked Confluence overview: DPLAT/02-connector-framework-overview

Return ONLY the JSON object.
```

(Повторить для EPIC-02 … 05.)

#### 7.3.2 Jira Story

```
SYSTEM:
You are generating a synthetic Jira Story in JSON for the DPLAT demo project.
Same product universe and domain language as before. Output a single JSON object
matching this schema (no prose, no fences):

{
  "key": "DPLAT-NNN",
  "issuetype": "Story",
  "project_key": "DPLAT",
  "epic_link": "DPLAT-EPIC-XX",
  "summary": "<short title in user-story style>",
  "description_md": "<As a [role], I want ... so that ...> + Background + numbered Acceptance criteria (3-6)",
  "priority": "High|Medium|Low",
  "status": "To Do|In Progress|Done",
  "labels": ["module:<id>", "feature:<id>", "role:<id>", "behavior:intended"],
  "components": ["<module name>"],
  "fix_versions": ["v2.3"],
  "affects_versions": [],
  "reporter": "<plausible email>",
  "assignee": "<plausible email>",
  "created": "<ISO date in 2026 Q1-Q2>",
  "updated": "<later ISO date>",
  "resolved": "<if Done: ISO date; else null>",
  "linked_issues": [{"type": "relates", "key": "<another DPLAT key>"}],
  "linked_confluence": [{"space": "DPLAT", "slug": "<relevant page slug>"}],
  "comments": [
    {"author": "<email>", "created": "<ISO>", "body_md": "<plausible review/QA comment>"}
  ]
}

Rules:
- description_md starts with a single "As a ... I want ... so that ..." line.
- Acceptance criteria are concrete and testable.
- Labels MUST include exactly one feature:* label and at least one role:* label.
- behavior:intended is mandatory for stories.
- 1–3 comments are realistic; do not invent threading.

USER:
Generate the Story with this identity:
- key: DPLAT-002
- title: "Salesforce connector — initial setup wizard"
- epic: DPLAT-EPIC-01
- feature: F-A1
- primary role: workspace-admin
- linked Confluence: DPLAT/04-salesforce-connector-business-rules
- linked Jira: DPLAT-003 (blocks), DPLAT-DEF-02 (relates)
- status: Done, fix_version v2.3

Return ONLY the JSON object.
```

(Повторить 15 раз с разными identity-блоками. Identity-блоки заранее зафиксированы в `SEEDS.md`.)

#### 7.3.3 Jira Requirement

Те же поля, `issuetype: "Task"` или кастомный `Requirement`, упор на non-functional: latency budgets, SLA, security, retention. Заранее задать 10 identity-блоков.

#### 7.3.4 Jira Defect

```
SYSTEM:
You are generating a synthetic Jira Bug (Defect) ticket in JSON. Same product
universe and schema as before, but issuetype is "Bug" and labels MUST include
"behavior:defect" (NOT behavior:intended). The description must clearly state:
- what was observed (broken behavior),
- what was expected,
- repro steps,
- workaround if any.

The defect describes broken behavior — DO NOT phrase it as if it were the intended
behavior. The downstream documentation generator must be able to tell that this is
a known issue, not the spec.

USER (example for the conflict-with-Confluence defect):
- key: DPLAT-DEF-04
- title: "Default retention period for cached connector data is 90d, not 30d as documented"
- feature: F-A1
- linked Confluence: DPLAT/04-salesforce-connector-business-rules (the rule says 30d)
- status: Open
- labels: module:connector-framework, feature:F-A1, behavior:defect, severity:medium, area:retention
- comments: at least one comment from compliance-officer raising concern

Return ONLY the JSON object.
```

#### 7.3.5 Confluence page

```
SYSTEM:
You are generating a synthetic Confluence page in Markdown WITH YAML frontmatter
for the DPLAT space. Output exactly one document; the first 4000 characters are
the page; do not output anything else (no prose around it, no fenced ```).

Format:
---
space: DPLAT
slug: <slug>
title: "<exact title>"
parent_slug: <slug or null>
labels:
  - <one or more labels matching the conventions used in Jira>
author: <plausible email>
created: <ISO>
updated: <ISO>
version: <integer>
status: current        # or "superseded" if legacy
linked_jira:
  - <DPLAT-XXX keys>
---

# <title>

<body — 400-1200 words depending on type. Use H2/H3 sections, bullet lists,
small tables where natural. Domain language: connector, retention, audit log, etc.>

Rules:
- Frontmatter values must be valid YAML.
- linked_jira contains keys that should plausibly exist (you'll be told which).
- Do NOT invent features outside the SEEDS table.
- For doc-type "business-rules" pages, the body MUST contain a single
  "source of truth" sentence that states the intended behavior on the dimension
  named in the user message (e.g. retention, sync frequency, error semantics).

USER (example for the conflict source page):
Generate a Confluence page with this identity:
- slug: 04-salesforce-connector-business-rules
- title: "Salesforce Connector — Business Rules"
- parent_slug: 02-connector-framework-overview
- doc-type: business-rules
- labels: [module:connector-framework, feature:F-A1, doc-type:business-rules, source-of-truth]
- linked_jira: [DPLAT-001, DPLAT-002, DPLAT-REQ-03]
- status: current
- The "source of truth" dimension is RETENTION: the page must clearly state that
  the default retention for cached connector data is 30 days. (This will later
  be intentionally contradicted by DPLAT-DEF-04 which claims 90 days.)
- Sections expected: Purpose, Object scope, Sync frequency, Authentication,
  Error handling, Retention of cached data.

Return ONLY the page (frontmatter + body).
```

Для legacy-страницы 09:

```
USER (legacy/superseded page):
Generate a Confluence page with this identity:
- slug: 09-pii-tagging-initial-design-LEGACY
- title: "PII Tagging — Initial Design (Legacy)"
- parent_slug: 03-compliance-vault-overview
- doc-type: design
- labels: [module:compliance-vault, feature:F-B1, doc-type:design, superseded]
- linked_jira: [DPLAT-005]   (the new story that replaces this design)
- status: superseded
- updated: "2024-04-12T10:00:00Z"  (intentionally old)
- The page describes an INITIAL design where PII tagging was rule-based only,
  ran post-ingestion, and supported only English. The CURRENT implementation
  (described in the new story DPLAT-005) is hybrid rule+ML, runs at ingestion,
  and supports EN/DE/FR. The legacy page should NOT mention this is outdated;
  the staleness must be detected by Metatron via dates + status label, not by
  copy-paste.

Return ONLY the page.
```

#### 7.3.6 Skeleton

```
SYSTEM:
You are generating a documentation skeleton in YAML for the DPLAT demo. The
skeleton drives section-level retrieval — each section declares the questions
to ask the knowledge base and the metadata filters to apply.

Schema:
guide: user-guide | admin-guide
audience: [<roles>]
sections:
  - id: <number>
    title: <string>
    feature: <feature id, optional>
    intent: <one-paragraph hint, optional>
    retrieval:
      questions: [<3-6 retrieval questions>]
      filters:
        labels_any: [<labels>]      # at least one must match
        labels_none: [<labels>]     # must NOT match (e.g. behavior:defect)
        roles: [<roles>]
    sections_required: [<list of subsection titles>]
    children:
      - <recursive same shape>

USER (user guide):
Build the User Guide skeleton covering features F-A1, F-A2, F-B1.
Audience: end-user and workspace-admin.
Sections:
- 1.0 Introduction
- 2.0 Getting started
  - 2.1 Salesforce connector setup (F-A1)
  - 2.2 SAP S/4 connector setup (F-A2)
- 3.0 Working with PII tagging (F-B1)
- 4.0 Common errors
- 5.0 FAQ
For each leaf section, include retrieval.questions (3-6), retrieval.filters,
and sections_required (4-6 subsections like "Prerequisites", "Steps",
"Verification", "Troubleshooting").

Return ONLY the YAML.
```

(Аналогично для admin-guide.)

#### 7.3.7 Bitbucket README

Короткий промпт, главное — упоминания feature-id, упоминания "Configuration", env-переменные, ссылки на DPLAT-XXX и Confluence-страницы (как обычные текстовые упоминания, без чудес).

### 7.4 Validator (обязательно прогнать после генерации)

Маленький локальный скрипт, чтобы поймать дрейф моделей. Псевдокод:

```python
# scripts/validate_demo_data.py
def validate():
    keys = load_jira_keys()                           # все DPLAT-* ключи
    pages = load_confluence_slugs()
    # 1. Все linked_issues в jira/* указывают на существующие keys
    # 2. Все linked_confluence в jira/* указывают на существующие slugs
    # 3. Все linked_jira в confluence/* указывают на существующие keys
    # 4. У каждой story есть feature:* label
    # 5. У каждого defect есть behavior:defect label
    # 6. quality signals C1–C6 присутствуют:
    #    - DPLAT-DEF-04 содержит "90 days" в description_md
    #    - DPLAT/04-...-business-rules содержит "30 days"
    #    - DPLAT/09-...-LEGACY имеет status: superseded и updated < 2025
    #    - не существует источника со словосочетанием "audit log retention" (для C3)
    # 7. Каждый feature имеет хотя бы одну Confluence-страницу с label source-of-truth
    # 8. Все даты ISO-8601, в диапазоне 2024-2026
```

Без этого этапа демо рискует сломаться неожиданно.

---

## 8. Loading data into the demo systems

Два пути. Лучше иметь оба готовыми; **на самой презентации использовать один** в зависимости от условий (есть интернет / есть Atlassian sandbox / клиент хочет видеть Atlassian).

### 8.1 Path A — Atlassian Cloud sandbox (рекомендуется)

Free Atlassian Cloud tenant с 1 пользователем, отдельный project `DPLAT`, отдельный space `DPLAT`. Один раз настроить — потом seed-скрипт полностью идемпотентен.

Подготовка:
1. Создать free Atlassian Cloud тенант (демо-почта).
2. Создать project `DPLAT` (Software, Scrum). Включить issue type `Bug` и `Task`.
3. Включить custom field "Epic Link" (если Cloud — оно есть).
4. Создать space `DPLAT` в Confluence.
5. Сгенерировать API token, положить в `.env`.

Seed-скрипты:

```python
# seed/seed_jira.py — pseudo-spec
# Reads jira/*.json, POSTs to Jira REST.
#  1) For each Epic: POST /rest/api/3/issue
#  2) For each Story/Task/Bug: POST /rest/api/3/issue with epic link
#  3) For each linked_issues: POST /rest/api/3/issueLink
#  4) For each comment: POST /rest/api/3/issue/{key}/comment
# Idempotent: if a key already exists (search via JQL), skip create.
# Set custom field "Epic Link" via the project's epic-link customfield id.
```

```python
# seed/seed_confluence.py
# Reads confluence/DPLAT/*.md, splits frontmatter, converts md→Confluence storage XML,
# POSTs to /wiki/rest/api/content with type=page, space=DPLAT.
# - Use a markdown-to-storage converter (mistune + custom renderer, or
#   third-party like 'md2cf'); be careful with admonitions, links, tables.
# - Apply labels via /wiki/rest/api/content/{id}/label
# - Set parent via {ancestors: [{id: parent_id}]}
# - Idempotent: if title already exists in space, update instead of create.
```

Запуск:

```bash
# Нужен интернет
python seed/seed_jira.py        --base https://amisol-demo.atlassian.net --user … --token …
python seed/seed_confluence.py  --base https://amisol-demo.atlassian.net --user … --token …
```

Затем в Metatron:

```bash
# Создать connection через UI или API
curl -X POST $METATRON/api/v1/connections -d '{
  "connector_type": "jira",
  "name": "DPLAT-demo",
  "config": {"url": "https://amisol-demo.atlassian.net", "username": "...",
             "api_token": "...", "project_key": "DPLAT"}
}'
# Аналогично для Confluence
# Затем POST /api/v1/connections/{id}/sync
```

Это **самый сильный demo path**: клиент видит, что Metatron реально дёргает Atlassian REST.

### 8.2 Path B — Direct Metatron ingestion (offline-safe)

Если интернета на демо нет, или клиент не хочет видеть «сторонний Jira», или мы не успели поднять Atlassian sandbox — заливаем JSON / MD прямо в Metatron, мимо Atlassian, с правильным `source_type` и метаданными. Demo выглядит так же, потому что генератор-агент задаёт вопросы Metatron'у, не Атлассиану.

Два варианта:

**B.1.** Через MCP `metatron_store` — каждый артефакт как отдельный документ. Подходит, если Metatron уже настроен и мы хотим показать MCP сразу.

**B.2.** Через REST `POST /api/v1/files/` (загрузка) или прямой ingestion API. Проще для batch'а.

Скрипт (псевдокод):

```python
# seed/seed_metatron_direct.py
# For each jira/*.json:
#   - render to markdown using the same structure jira_issue_to_markdown emits
#     (so retrieval-side rendering is identical to the real connector)
#   - POST /api/v1/documents with:
#       source_type: "jira"
#       source_id: <key>
#       url: f"https://demo-jira.local/browse/{key}"
#       title: f"[{key}] {summary}"
#       content: <markdown>
#       metadata: {issue_key, status, assignee, ...}   # mirror jira.py:_issue_to_document
#       tags: <labels>
# For each confluence/*/*.md:
#   - parse frontmatter
#   - body becomes content
#   - source_type: "confluence", source_id: page_id (synth, e.g. hash of slug)
#   - url: f"https://demo-confluence.local/wiki/spaces/{space}/pages/{page_id}"
#   - metadata mirrors confluence.py:_page_to_document
# For bitbucket README — source_type "github" (closest), mark as repo_readme.
```

Это путь специально написан так, чтобы **payload в Metatron был неотличим** от того, что emit'ит реальный connector. Тогда retrieval, scoring, recall channels — всё работает 1:1 без подмены.

> Замечание для команды: `FilesConnector.fetch()` сейчас scaffold (`NotImplementedError`). Не использовать его для seed'а. Если хочется именно через FilesConnector — это отдельная маленькая задача (`MTRNIX-XXX`), но для демо она не нужна.

### 8.3 Какой путь выбрать на самом демо

| Условие | Path |
|---------|------|
| есть интернет, есть Atlassian sandbox, есть 30 минут до клиента | A |
| нет интернета, или клиент хочет «just Metatron» | B |
| хочется показать «AI-agnostic» — внешний Hermes/Claude Desktop поверх | A или B (без разницы) |

Готовить **оба** — Path B как fallback в кармане.

---

## 9. Demo script (15–20 минут)

| t | Сцена | Что показываем | Что говорим (заготовка) |
|---|-------|---------------|--------------------------|
| 00:00 – 02:00 | Setup | Скриншот Jira с DPLAT issues + Confluence с DPLAT pages + skeleton YAML | "Это ваш типичный мир в миниатюре: 5 фичей, 40+ артефактов, два гайда." |
| 02:00 – 04:00 | Ingestion | Запустить sync (A) или показать, что данные уже залиты (B); счётчики Documents/Chunks | "За один проход Metatron собрал источники в гибридный индекс — вектор + граф + метаданные." |
| 04:00 – 09:00 | **User Guide page** | Нажать «Generate § 2.1 Salesforce connector setup» в demo-UI или вызвать MCP `metatron_search` через Claude Desktop / Hermes. Показать сгенерированную страницу с цитатами. | "Генератор не пишет всю страницу одним промптом — он идёт секция за секцией, каждой секции свой retrieval-запрос. Каждый абзац подписан источником." |
| 09:00 – 12:00 | **Admin Guide page** | Сгенерировать страницу для того же feature, но с audience admin/compliance. Показать, как подсветились permissions/config. | "Один и тот же индекс — две разных страницы, потому что фильтры разные. Юзер не видит админский knob, и наоборот." |
| 12:00 – 14:00 | **Quality flags** | Показать секцию Retention со значком ⚠ conflict — три источника, три разных числа, агент явно говорит «нужен SME». Показать stale-страницу 09 с пометкой superseded. Показать секцию Audit Log Retention с явным "no source". | "Мы не сглаживаем противоречия. Это самое важное для compliance-документации — лучше явно сказать «не уверены», чем выдумать." |
| 14:00 – 17:00 | **Второй use case** | Тот же индекс, новый промпт: "Compliance officer asks: how do we comply with GDPR Art. 30 records of processing for the connector layer?" — собрать ответ с цитатами. Или: сгенерировать marketing tagline для F-B1 с цитатами на business-rules. | "Это не отдельный pipeline. Тот же KB, другой агент, другой промпт. Ваш CEO получит тот же шаблон ответа на compliance-опросник, который уже сейчас прошёл через тот же индекс." |
| 17:00 – 19:00 | (опц.) **AI-agnostic showcase** | Открыть Claude Desktop / Cursor / OpenWebUI — показать, что MCP-tool `metatron_search` работает оттуда же, выдаёт те же источники. | "Если завтра вы сменили модель с Azure OpenAI на on-prem Llama — KB остаётся. Не переделываем pipeline." |
| 19:00 – 20:00 | Wrap-up | Показать список, что осталось вне демо: live data под NDA, eval harness, SME review, OAuth permissions propagation. | "Это синтетика. Когда подпишем NDA — поднимаем то же самое в вашей secure среде, поверх ваших ~100 страниц и тысяч issues." |

**Ключевые моменты постановки:**
- Два разных «оркестратора» в демо: Doc-Generator agent (наш) и MCP-клиент (Claude Desktop). Это и есть «AI-agnostic».
- НЕ показывать Neo4j browser, Qdrant UI, eval-цифры, бэкенд-логи. Только результат и цитаты.
- Демо-страница должна **визуально отличать** обычный текст от цитаты — иконка 📄 и em-dash, как уже сделано в Metatron (`{icon} {title} — {url}`).

---

## 10. Output design — what the agent's answer should look like

Это, наверное, самая стратегическая часть для клиента. «How should the answer look?» — потому что **тот же ответный объект будет потреблять не один агент**, а 5+ (документатор, code-review, scrum, compliance, marketing). Нужен один общий контракт.

### 10.1 Section-level, не page-level

Главное архитектурное решение: **агент генерирует не страницу, а массив секций**. Страница — это композиция секций. Это даёт:
- частичный re-render: изменилась только секция Retention — пересчитываем только её;
- параллелизм: 6 секций — 6 запросов к KB одновременно;
- честный SME-review: SME approve'ит секции, не страницы;
- traceable diff: между двумя версиями страницы видно, какая секция протухла.

### 10.2 Output schema (строгий JSON)

Этот JSON — то, что Doc-Generator agent возвращает; downstream-инструмент (Confluence-publisher, Markdown-renderer, SME-review-UI) читают его без догадок.

```json
{
  "doc_id": "user-guide/2.1",
  "guide": "user-guide",
  "section_id": "2.1",
  "title": "Setting up a Salesforce connector",
  "feature": "F-A1",
  "audience": ["end-user", "workspace-admin"],
  "generated_at": "2026-05-02T14:30:00Z",
  "model": "claude-opus-4-7",
  "skeleton_version": "user-guide.yaml@v3",
  "status": "draft",                      // draft | sme_review | published | stale
  "subsections": [
    {
      "id": "2.1.1",
      "title": "Prerequisites",
      "body_md": "Before you start, make sure you have:\n- A Salesforce …",
      "claims": [
        {
          "text": "The user must have System Administrator profile in Salesforce.",
          "citations": [
            {"source_type": "confluence", "source_id": "DPLAT/04-...-business-rules",
             "url": "...", "section": "Authentication", "snippet": "Requires SF SysAdmin..."}
          ],
          "confidence": "high"
        }
      ],
      "flags": []                         // empty when clean
    },
    {
      "id": "2.1.4",
      "title": "Retention of cached data",
      "body_md": "⚠ Conflicting information. According to the business rules ... 30 days. According to a recently logged defect, the actual default is 90 days. Subject to SME review.",
      "claims": [
        {"text": "Default retention is 30 days.", "citations": [{...DPLAT/04...}], "confidence": "medium"},
        {"text": "Actual default is 90 days (defect logged 2026-04-15).", "citations": [{...DPLAT-DEF-04...}], "confidence": "medium"}
      ],
      "flags": [
        {"kind": "conflict",
         "dimension": "retention",
         "sources": ["confluence:DPLAT/04-...-business-rules", "jira:DPLAT-DEF-04", "jira:DPLAT-006"],
         "needs_sme": true}
      ]
    },
    {
      "id": "2.1.5",
      "title": "Audit log retention",
      "body_md": "_No information available in the connected sources. Please consult the Compliance Officer._",
      "claims": [],
      "flags": [
        {"kind": "missing", "questions_asked": [
          "What is the audit log retention period for the Salesforce connector?",
          "How long are connector audit events stored?"
        ]}
      ]
    }
  ],
  "page_flags": [],                       // page-level: e.g. "skeleton mismatch", "audience leak"
  "review": {
    "required": true,
    "reasons": ["conflict in 2.1.4", "missing in 2.1.5"],
    "assignees": ["compliance-officer"]   // derived from feature.role mapping
  }
}
```

### 10.3 Citation format

Совпадает с тем, что уже отдаёт Metatron в pipeline (`{icon} {title} — {url}`), плюс дополнительные машинные поля для downstream:

```json
{
  "source_type": "jira | confluence | github | upload | notion",
  "source_id":   "<DPLAT-002 / DPLAT/04-... / repo#path>",
  "title":       "[DPLAT-002] Salesforce connector — initial setup wizard",
  "url":         "https://...",
  "section":     "Acceptance criteria",        // when retrieval localized to a section
  "snippet":     "AC2: When the OAuth flow ...",
  "evidence_role": "primary | supporting",     // matches metatron pipeline naming
  "retrieved_score": 0.71                       // metatron final score
}
```

`evidence_role` напрямую из `_mark_evidence_role` в retrieval pipeline — **переиспользуем существующую сигнатуру**, не выдумываем новую.

### 10.4 Flag taxonomy

Жёстко зафиксирован — и агенты-потребители знают, что обрабатывать.

| flag.kind | when | downstream effect |
|-----------|------|-------------------|
| `conflict`     | retrieval вернул ≥2 источника с противоречивыми утверждениями по одному `dimension` | секция помечена `needs_sme`, в UI ⚠, в JSON `review.required = true` |
| `stale`        | первичный источник имеет `superseded` label или `updated < threshold` | страница не блокируется, но в footer плашка «based on data from <date>» |
| `missing`      | retrieval вернул empty / только tangentially-related | секция явно говорит "no source", `review.required = true` |
| `defect-mention` | в pool попал источник с `behavior:defect` | агент не использует его для intended behavior; либо вытесняет в "Known issues", либо игнорирует |
| `permission-leak` | retrieval достал документ с ролью, не входящей в audience | секция дропается; страница помечается page-level флагом |
| `low-confidence` | reranker score < threshold для всех claim'ов | confidence: "low", в UI бледный шрифт |

### 10.5 Почему этот контракт переживёт смену агентов

- Confluence-publisher читает только `body_md` секций.
- SME-review-UI читает `flags` + `claims` + `review`.
- Code-review-агент читает `claims[].text` + `citations[].source_id` (см. §11.2).
- Compliance-questionnaire-агент берёт тот же объект и собирает ответ из `claims` с `confidence ≥ medium`.
- Marketing-агент использует `claims` как fact-check — текст пишет сам, но не противоречит claim'ам.
- Любая смена LLM не ломает downstream — контракт стабилен.

---

## 11. Multi-agent integration (beyond Metatron itself)

Демонстрировать всё это во время первой встречи **не нужно**, но в follow-up материале и в архитектурном слайде — обязательно. Клиент в Confluence-статье прямо называет: PR-review, QA-помощник, генерация тест-кейсов, документация, маркетинг, sales, legal, compliance, customer chatbot. То есть документация — лишь первая дверь.

### 11.1 Doc-Generator agent (главный герой demo)

- **Входные данные:** skeleton YAML + feature id.
- **Что делает:** §10.1 + §10.2.
- **Куда живёт:** где угодно — наш собственный мини-сервис, либо как промпт в Hermes, либо как Claude Skill, либо как кастомный GPT поверх OAI-compat.
- **MCP-зависимости:** `metatron_search`, опционально `metatron_get` для подтягивания полного источника.

### 11.2 Code-review agent (PR review against acceptance criteria)

- **Триггер:** webhook от Bitbucket на open PR.
- **Что делает:** парсит JIRA-ключ из branch name / PR title, дёргает `metatron_get(jira:DPLAT-XXX)` за acceptance criteria, прогоняет diff против них.
- **Использует тот же contract:** результат — список `claims` с `verdict ∈ {satisfied, missing, ambiguous}` и `citations` на конкретные строки кода + AC.
- **Ключевое:** не нужен отдельный индекс — тот же KB, другая проекция.

### 11.3 Scrum-master agent

- **Триггер:** еженедельный cron + on-demand.
- **Что делает:** "show me defects open >30d on F-A1, with their related stories and any mentions in Confluence troubleshooting pages". Это запрос с graph-traversal и temporal filter — то, для чего Metatron собственно и существует.
- **Output:** structured table → Slack message / dashboard.

### 11.4 Compliance / questionnaire agent

- **Триггер:** загрузка Excel с вопросами от клиента / регулятора.
- **Что делает:** для каждого вопроса — retrieval + draft answer + citations + uncertainty.
- **Same contract:** возвращает массив `{question, answer_md, claims, citations, confidence, review_required}`.
- **Demo-уловка:** один и тот же синтетический KB реально может ответить на 2–3 заранее заготовленных compliance-вопроса. Покажем именно это.

### 11.5 Marketing copy agent

- Принимает `claims[]` как hard-fact список, генерирует прозу — но **не имеет права** утверждать вне списка.
- Это закрывает риск, который Amisol упоминала в discovery call (LLM galloping).

### 11.6 Integration patterns (как они подключаются)

| Surface | Кто | Как |
|---------|-----|-----|
| **MCP** | Hermes, Cursor, Claude Desktop, OpenClaw, любой MCP-агент | bearer `METATRON_MCP_API_KEY`, tools `metatron_search` / `metatron_get` / `memory_search` |
| **OAI-compat /v1/chat** | LibreChat, OpenWebUI, любой OAI-клиент | `mtk_...` ключ, `model: metatron-rag-{workspace}` |
| **REST /api/v1** | кастомные сервисы (PR-review бот, scrum cron) | JWT, прямой доступ ко всему |

Слайд: «один индекс — три surface — N агентов». Это ровно та история, которую нужно продать после demo.

---

## 12. Risks & mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Локальный LLM генерирует невалидный JSON, ссылки не разрешаются | high | §7.4 валидатор + одна попытка → одна правка вручную; держать `qwen2.5` с `format: json` |
| Confluence storage XML конвертация ломает таблицы / admonitions | medium | использовать готовый `md2cf`, заранее протестировать на одной странице; иметь `Path B` как fallback |
| Atlassian sandbox tenant был приостановлен | medium | заранее прогреть пинг за день; иметь Path B готовый |
| На демо вопрос «а если у нас 100k issues, а не 40?» | high | заготовить ответ: hybrid retrieval scales; показать, что pipeline не зависит от количества — он зависит от метаданных |
| «А вы видите наши данные?» | high | сразу показать: synthetic data, NDA после demo; никакого live-доступа в первой встрече |
| Reranker регрессия на маленьком корпусе | medium | реранкер на 40 документах может не отделить хорошее от плохого — заранее проверить и при необходимости отключить (`RERANKER_ENABLED=false`) на демо |
| Спорный кейс: defect упоминается в User Guide | high | C6 — promised behavior; обязательно прогнать руками перед демо |
| Время вышло, не доехали до второго use case | medium | second use case — самая важная часть для CEO-нарратива; держать как первую часть, не последнюю, если время поджимает |

---

## 13. Pre-demo checklist (сделать до встречи)

- [ ] Сгенерировать `demo-data/` целиком (~3-4 часа на лаптопе).
- [ ] Прогнать `validate_demo_data.py` — все 6 quality signals подтверждены.
- [ ] Поднять Atlassian sandbox + загрузить через `seed_jira.py` + `seed_confluence.py`. Сделать скриншоты на всякий случай.
- [ ] Альтернативно: загрузить через `seed_metatron_direct.py` (Path B) и убедиться, что retrieval для трёх контрольных запросов даёт ожидаемые источники.
- [ ] Прогнать demo-flow целиком от начала до конца **дважды** — один раз дома, один раз с нашим мейтом-«клиентом».
- [ ] Подготовить 1–2 дополнительных compliance-вопроса для второго use case (заранее проверить, что синтетика на них отвечает).
- [ ] Подготовить слайд `one index → three surfaces → N agents` (§11.6).
- [ ] Заготовить ответы на типовые возражения: scaling, on-prem, multi-tenant, model-agnostic, permissions propagation.
- [ ] Подготовить follow-up письмо (см. §14 Confluence-статьи — там уже есть черновик; обновить под результаты demo).

---

## 14. Open questions for the team

1. **Path A или Path B на самом demo?** Нужно решить заранее, не на лету. Я склоняюсь к A (Atlassian Cloud sandbox) — сильнее визуально, демонстрирует connector в работе. B держим как fallback.
2. **Какая фича — герой demo?** Я предлагаю F-A1 (Salesforce Connector) — самая «нормальная» с UI-flow + admin knobs. F-B1 (PII Tagging) хороша для второго use case (compliance). F-A3 (Connector Health Monitor) — кандидат для admin-only страницы.
3. **Doc-Generator agent — где живёт?** Варианты: (a) маленький Python сервис у нас; (b) Claude Skill поверх MCP; (c) кастомный GPT поверх OAI-compat; (d) Hermes-флоу. Я предлагаю (a) для управляемости + (b) показать что это работает и через внешнего клиента.
4. **Демо-UI — что используем?** Можно показать в Markdown-viewer, можно в нашем будущем Control Center, можно собрать одну страничку на FastAPI templates за час. Достаточно простого split-view: skeleton слева, generated сверху, citations снизу.
5. **MTRNIX-XXX задача под этот demo?** Думаю да — заведём `MTRNIX-DEMO-AMISOL-01` (или просто `MTRNIX-XXX feat: amisol demo prep`) с подзадачами: data gen, sandbox setup, doc-generator agent, demo-UI, dry-run.
6. **Метаданные клиента — какой минимум обязательный?** Нужно зафиксировать: `module`, `feature`, `role`, `version`, `behavior:intended/defect`, `status` (current/superseded), `audience`. Это и есть ответ на их вопрос «what metadata do we need».
7. **Eval harness в demo-1 — нет, в demo-2 — да.** Подготовить 5 golden questions на нашей синтетике сейчас, чтобы при follow-up показать «у нас есть способ это измерить».

---

## 15. Appendix A — что положить в `demo-data/SEEDS.md`

Заранее зафиксированная таблица идентичности всех артефактов. LLM не должна это придумывать, иначе ссылки разъедутся. Шаблон:

```
# SEEDS — fixed identity table for DPLAT demo data
# Treat as authoritative; LLM prompts must reference these exact ids.

## Modules
MOD-A  Connector Framework
MOD-B  Compliance Vault

## Features
F-A1   Salesforce Connector       (in MOD-A)
F-A2   SAP S/4 Connector          (in MOD-A)
F-A3   Connector Health Monitor   (in MOD-A, admin-only)
F-B1   PII Auto-Tagging           (in MOD-B)
F-B2   Audit Log Export           (in MOD-B, admin-only)

## Roles
ROLE-EU end-user
ROLE-WA workspace-admin
ROLE-CO compliance-officer

## Jira
DPLAT-EPIC-01  Salesforce Connector              feature=F-A1
DPLAT-EPIC-02  SAP S/4 Connector                  feature=F-A2
DPLAT-EPIC-03  Connector Health Monitor          feature=F-A3
DPLAT-EPIC-04  PII Auto-Tagging                  feature=F-B1
DPLAT-EPIC-05  Audit Log Export                  feature=F-B2

DPLAT-001  Story  F-A1  end-user setup overview
DPLAT-002  Story  F-A1  initial setup wizard               role=workspace-admin   conf=04
DPLAT-003  Story  F-A1  OAuth refresh flow                 role=workspace-admin
DPLAT-004  Story  F-A2  initial setup wizard               role=workspace-admin
DPLAT-005  Story  F-B1  hybrid rule+ML PII classifier      role=compliance-officer  supersedes=conf-09
DPLAT-006  Story  F-B1  per-tenant retention override      role=workspace-admin
…

DPLAT-REQ-01  Requirement  F-A1  connector latency budget
DPLAT-REQ-02  Requirement  F-A1  rate-limiting policy
…

DPLAT-DEF-01  Bug  F-A1  OAuth refresh fails on weekend cron       behavior=defect
DPLAT-DEF-02  Bug  F-A1  Linked to story DPLAT-002 (relates)        behavior=defect    conf=04
DPLAT-DEF-04  Bug  F-A1  Default retention is 90d not 30d           behavior=defect    conflict_with=conf-04
DPLAT-DEF-07  Bug  F-B1  PII tagging skips emails in CSV imports    behavior=defect
…

## Confluence (space=DPLAT)
01  product-overview
02  connector-framework-overview                module=MOD-A   parent=01
03  compliance-vault-overview                   module=MOD-B   parent=01
04  salesforce-connector-business-rules         feature=F-A1   parent=02   labels=[source-of-truth]
05  pii-auto-tagging-policy                     feature=F-B1   parent=03   labels=[source-of-truth]
06  connector-config-api                        module=MOD-A   parent=02   doc-type=api-spec
07  salesforce-connector-troubleshooting        feature=F-A1   parent=02   doc-type=troubleshooting
08  release-notes-v2-3                          parent=01      doc-type=release-notes
09  pii-tagging-initial-design-LEGACY           feature=F-B1   parent=03   status=superseded   updated=2024-04
10  getting-started-DRAFT                       parent=01      doc-type=draft

## Bitbucket
connector-framework / README.md       refs F-A1, F-A2, F-A3
compliance-vault    / README.md       refs F-B1, F-B2
shared-libs         / README.md       refs all features briefly

## Quality signals (must hold after generation)
C1  conflict   conf-04 (30d)  vs  DPLAT-DEF-04 (90d)  vs  DPLAT-006 (60d)
C2  staleness  conf-09 (2024-04, superseded)  vs  DPLAT-005 (2026-04)
C3  missing    no source covers retention of audit_log (F-B2)
C4  cross-link DPLAT-002  ←→  conf-04  ←→  DPLAT-DEF-02
C5  perm-split F-B2 only in admin-guide; F-A1 wizard only in user-guide
C6  defect≠beh DPLAT-DEF-07 must NOT appear as intended behavior in user-guide
```

---

## 16. Appendix B — minimal commands cheatsheet

```bash
# ── 0. One-time setup (уже сделано на машине Konstantin'а) ──────────
# omlx установлен в /opt/homebrew/bin/omlx
# Модели засимлинкованы в ~/.omlx/models/ → ~/.cache/huggingface/hub/...
# settings.json: host=127.0.0.1, port=8090

# ── 1. Поднять oMLX (в отдельном терминале) ─────────────────────────
omlx serve --port 8090

# Проверить, что сервер жив
curl -s http://127.0.0.1:8090/v1/models | jq

# ── 2. Локальная генерация артефактов ────────────────────────────────
python scripts/gen.py prompts/payloads/DPLAT-002         # один артефакт
python scripts/gen.py prompts/payloads/                   # все недостающие (идемпотентно)

# Если в settings.json включён api_key:
OMLX_API_KEY=<key> python scripts/gen.py prompts/payloads/

# Альтернатива через curl (один Jira issue с json_schema, см. §7.1.4)
jq -n --slurpfile schema prompts/schemas/jira_issue.schema.json \
      --rawfile  systxt  prompts/system/jira_story.system.txt \
      --rawfile  usertxt prompts/payloads/DPLAT-002.user.txt \
   '{model:"qwen36-a3b", temperature:0.4, max_tokens:2000,
     response_format:{type:"json_schema", json_schema:$schema[0]},
     messages:[{role:"system",content:$systxt},{role:"user",content:$usertxt}]}' \
  | curl -s http://127.0.0.1:8090/v1/chat/completions \
         -H "Content-Type: application/json" -d @- \
  | jq -r '.choices[0].message.content' > demo-data/jira/DPLAT-002.json

# ── 3. Валидация ────────────────────────────────────────────────────
python scripts/validate_demo_data.py demo-data/

# ── 4a. Path A — push в Atlassian sandbox (нужен интернет) ───────────
python seed/seed_jira.py        --base $JIRA_URL  --user $USER --token $TOKEN
python seed/seed_confluence.py  --base $CONF_URL  --user $USER --token $TOKEN

# ── 4b. Path B — push напрямую в Metatron (offline-friendly) ─────────
python seed/seed_metatron_direct.py --base http://localhost:8000 --workspace demo

# ── 5. Sync Metatron с Atlassian (только Path A) ────────────────────
curl -X POST $METATRON/api/v1/connections/$JIRA_CONN_ID/sync
curl -X POST $METATRON/api/v1/connections/$CONF_CONN_ID/sync

# ── 6. Ping retrieval (sanity) ──────────────────────────────────────
curl -X POST $METATRON/api/v1/search -H "Content-Type: application/json" \
  -d '{"workspace_id":"demo","query":"How is the Salesforce connector authenticated?","top_k":5}'
```

---

## 17. References

- Source case: Confluence `MTRNIX/23756802` — *Client Case: Automated User Guide + Admin Guide from Jira and Confluence*.
- Strategy ADR: `docs/adr/2026-04-25-metatron-strategy.md` — context for Hermes integration, Memory Quality Layer, Permission Model v2.
- `docs/HERMES_INTEGRATION.md` — recommended external-agent setup; relevant for §11.6.
- `docs/MCP_API.md` — MCP tools surface used by `metatron_search` / `metatron_get`.
- `docs/CONNECTORS.md` — Jira / Confluence connectors used in Path A.
- Code anchors:
  - `src/metatron/connectors/jira.py:110` (`_issue_to_document`) — payload shape that Path B must mirror.
  - `src/metatron/connectors/confluence.py:166` (`_page_to_document`) — same.
  - `src/metatron/retrieval/search.py` — pipeline; `_mark_evidence_role` defines `primary | supporting`, reused in §10.3.
