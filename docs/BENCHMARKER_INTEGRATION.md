# Интеграция Metatron Benchmarker в Metatron Core

## 1. Контекст

Metatron Benchmarker — отдельный микросервис для автоматической оценки качества RAG-системы Metatron Core. Использует BenchmarkQED для генерации вопросов (AutoQ) и оценки корректности ответов (AutoE), а также набор LLM-as-Judge метрик.

Исходный код бенчмаркера скопирован в корень репозитория метатрона — папка `metatron-benchmarker/`. Используется как референс при интеграции. По завершении интеграции папка `metatron-benchmarker/` удаляется из репозитория.

Цель интеграции — перенести функционал бенчмаркера внутрь Metatron Core как модуль `src/metatron/benchmarker/`, переиспользуя существующую инфраструктуру метатрона (коннекторы, БД, LLM-провайдеры, конфиг).

## 2. Принципы интеграции

- Подход метатрона всегда приоритетнее: архитектура, паттерны, стиль кода.
- Новый код размещается в `src/metatron/benchmarker/` со своей внутренней структурой.
- Дублирующиеся модули (коннекторы, конфиг, БД-подключение) используются из метатрона.
- Существующий код метатрона не модифицируется, кроме: добавления роутов, миграции, конфиг-полей, зависимости.
- Фронтенд бенчмаркера уже интегрирован, в скоуп входит только бэкенд.

## 3. Архитектура модуля

```
src/metatron/benchmarker/
├── __init__.py
├── schemas/                    # Pydantic-модели бенчмаркера
│   ├── __init__.py
│   ├── benchmark.py            # BenchmarkQuestion, Claim, QuestionAttributes
│   ├── test_context.py         # TestContext, ChunkData
│   └── test_result.py          # BenchmarkTestResult
├── services/
│   ├── __init__.py
│   ├── generator.py            # BenchmarkGenerator (BenchmarkQED AutoQ)
│   ├── runner.py               # TestRunner — оркестрация тестов
│   ├── context_fetcher.py      # Получение white box данных (query logs, chunks)
│   ├── document_sampler.py     # Адаптер: коннекторы метатрона → документы для генерации
│   └── metrics/
│       ├── __init__.py
│       ├── controller.py       # MetricsController (в оригинале metrics_controller.py уровнем выше — рефакторинг)
│       ├── qed.py              # Correctness (BenchmarkQED AutoE)
│       ├── relevancy.py        # Answer Relevancy (embeddings)
│       ├── faithfulness.py     # Faithfulness (LLM as Judge)
│       ├── context_precision.py # Context Precision (LLM as Judge)
│       ├── context_recall.py   # Context Recall (LLM as Judge)
│       └── confidence.py       # Заглушка (возвращает score=1.0)
├── db/
│   ├── __init__.py
│   ├── models.py               # ORM-модели: BenchmarkSet, TestRun, TestResult
│   └── crud.py                 # CRUD-операции
└── api/
    ├── __init__.py
    ├── generation.py           # POST /generate
    ├── testing.py              # POST /run-tests
    ├── benchmarks.py           # CRUD бенчмарков
    └── test_runs.py            # CRUD тест-ранов
```

## 4. Коннекторы и получение документов

### Текущее состояние

| Аспект | Metatron Core | Benchmarker |
|--------|--------------|-------------|
| Интерфейс | `ConnectorInterface` (async `configure()` + `fetch()`) | `SourceConnector` (sync `fetch_documents(limit)`) |
| Назначение | Инкрементальный синк документов в воркспейс | Одноразовый сэмпл документов для генерации вопросов |
| Модель документа | `core.models.Document` (dataclass: `id`, `workspace_id`, `source_type`, `source_id`, `title`, `content`, `url`, `author`, `tags`, `metadata`, `created_at`, `updated_at`) | `schemas.Document` (Pydantic: `source_id`, `title`, `text`, `source_type`, `url`) |
| Лимит | Нет — фетчит всё | Есть — параметр `limit` |

### Решение

Используем коннекторы метатрона. Создаём `document_sampler.py` — адаптер, который:

1. Получает `Connection` из воркспейса (credentials уже есть в БД).
2. Инициализирует коннектор метатрона через `configure()`.
3. Вызывает `fetch(workspace_id)` — получает все документы.
4. Рандомно сэмплирует N документов из полученных.
5. Конвертирует `metatron.core.models.Document` → формат, ожидаемый генератором.

Маппинг полей:

```python
# metatron Document → benchmarker Document
{
    "source_id": doc.source_id,      # source_id → source_id
    "title": doc.title,              # title → title
    "text": doc.content,             # content → text
    "source_type": doc.source_type,  # source_type → source_type
    "url": doc.url,                  # url → url
}
```

### Конфликт: отсутствие лимита в коннекторах

Коннекторы метатрона не поддерживают `limit` в `fetch()`. Для MVP с небольшими спейсами фетчим все документы, сэмплируем на стороне бенчмаркера. Оптимизация (добавление `limit` в `ConnectorInterface`) — отдельная задача на будущее.

### Конфликт: sync vs async

Коннекторы метатрона — async. Генератор бенчмарков (BenchmarkQED) работает синхронно. Вызовы коннекторов делаются в async-контексте API-эндпоинта (await connector.fetch()), затем результат передаётся в генератор синхронно. Конфликта event loop нет — проблема с event loop относится только к BenchmarkQED (см. секцию 7).

## 5. Прямые вызовы вместо HTTP

### Текущее состояние (бенчмаркер)

```
TestRunner → HTTP POST /api/chat → Metatron Core → ответ + query_log_id
ContextFetcher → HTTP GET /api/query-logs/{id} → query log
ContextFetcher → HTTP GET Qdrant → chunks
```

### Решение

Заменяем `MetatronCoreClient` (HTTP) на прямой вызов компонента, стоящего за `/api/chat`:

```
TestRunner → прямой вызов chat-сервиса → ответ + query_log_id
ContextFetcher → прямой запрос в БД → query log
ContextFetcher → HTTP GET Qdrant → chunks (оставляем как есть)
```

Нужно определить, какой именно сервис/функция стоит за эндпоинтом `/api/v1/chat` и вызывать его напрямую. Сейчас это `hybrid_search_and_answer()` из `metatron.retrieval.search`. Это убирает сетевой оверхед и зависимость от запущенного API.

### Критично: retrieval-контекст недоступен снаружи

Текущий `ChatResponse` метатрона (`src/metatron/api/routes/chat.py`) возвращает только `answer` и `workspace_id`. Функция `hybrid_search_and_answer()` из `metatron.retrieval.search` возвращает строку. Все промежуточные данные (чанки со scores, graph enrichment, фрагменты контекста) существуют только внутри функции и теряются.

Бенчмаркеру эти данные нужны для white box метрик: Faithfulness, Context Precision и Context Recall работают с чанками, которые были использованы при генерации ответа.

### Решение: параметр `return_trace` в `hybrid_search_and_answer()`

Минимальная модификация — добавить опциональный параметр и условие перед return:

```python
def hybrid_search_and_answer(
    query: str, user_id: str = "user", k: int = 5,
    workspace_id: Optional[str] = None, intent_query: Optional[str] = None,
    return_trace: bool = False,          # ← новый параметр
) -> str | dict:
    # ... весь существующий код без изменений ...

    # перед финальным return:
    if return_trace:
        return {
            "answer": _append_sources(answer, base),
            "source_results": base,       # результаты поиска со scores
            "fragments": frags,           # фрагменты, отправленные в LLM
            "graph_entities": g_ents,
            "graph_relations": g_rels,
            "graph_docs": g_docs,
        }
    return _append_sources(answer, base)
```

Обратная совместимость полная — без `return_trace` поведение идентичное, возвращается строка. Все переменные (`base`, `frags`, `g_ents`, `g_rels`, `g_docs`, `answer`) уже существуют в скоупе функции к моменту return. Никакие другие части функции не затрагиваются.

Бенчмаркер вызывает с `return_trace=True` и получает всё необходимое для white box метрик напрямую, без промежуточного сохранения в БД.

## 6. База данных

### Новые таблицы

Добавляются через alembic-миграцию `005_benchmarker.py`:

```
benchmark_sets
├── id (PK, String)
├── workspace_id (FK → workspaces.id)    ← НОВОЕ: привязка к воркспейсу
├── name (String)
├── description (Text, nullable)
├── source (String)                       # jira/confluence
├── source_info (JSON, nullable)
├── created_at (DateTime)
├── tokens_used (Integer)
└── question_count (Integer)

benchmark_questions
├── id (PK, String)
├── benchmark_set_id (FK → benchmark_sets.id)
├── text (Text)
├── question_type (String)                # data_local/data_global
├── references (JSON, nullable)
├── attributes (JSON)                     # claims, coverage, similarities
└── created_at (DateTime)

test_runs
├── id (PK, String)
├── benchmark_set_id (FK → benchmark_sets.id)
├── name (String)
├── description (Text, nullable)
├── created_at (DateTime)
├── total_tests (Integer)
├── avg_correctness (Float, nullable)
├── avg_answer_relevancy (Float, nullable)
├── avg_faithfulness (Float, nullable)
├── avg_context_precision (Float, nullable)
├── avg_context_recall (Float, nullable)
└── avg_confidence (Float, nullable)

test_results
├── id (PK, String)
├── test_run_id (FK → test_runs.id)
├── question (JSON, nullable)             # снапшот вопроса
├── actual_answer (Text)
├── correctness (Float, nullable)
├── answer_relevancy (Float, nullable)
├── faithfulness (Float, nullable)
├── context_precision (Float, nullable)
├── context_recall (Float, nullable)
├── confidence (Float, nullable)
├── claim_scores (JSON, nullable)
└── context (JSON, nullable)              # white box данные
```

### SQLAlchemy: совместимость

Оба проекта используют синхронный SQLAlchemy для ORM: `create_engine`, `sessionmaker`, `Session`, `declarative_base()`. Конфликта нет. ORM-модели бенчмаркера переносятся с минимальными изменениями:

```python
from metatron.storage.pg_models import Base       # declarative_base()
from metatron.storage.pg_connection import get_session  # sync context manager
```

Единственная адаптация — замена `psycopg2-binary` на драйвер метатрона и подключение к общей БД.

### workspace_id

Все бенчмарки привязываются к `workspace_id`. Бенчмарк формируется из документов конкретного воркспейса, тестируется на нём же. FK на `workspaces.id` с `ON DELETE CASCADE`.

## 7. Метрики

MetricsController координирует параллельный запуск всех метрик. В оригинале `__init__()` принимает 9 параметров (API keys, URLs, models). При интеграции конфигурация должна приходить из `Settings` метатрона. Рекомендуется фабричный метод:

```python
class MetricsController:
    @classmethod
    def from_settings(cls, settings: Settings) -> "MetricsController":
        return cls(
            deepseek_api_key=settings.deepseek_api_key,
            embedding_base_url=settings.benchmarker_embedding_proxy_url,
            deepseek_base_url=settings.deepseek_base_url,
            ...
        )
```

Аналогично для `BenchmarkGenerator` и других сервисов с конфигурацией — фабрика `from_settings()` вместо ручной передачи параметров.

### 6 метрик бенчмаркера

| # | Метрика | Тип | Реализация | Зависимости |
|---|---------|-----|------------|-------------|
| 1 | Correctness | Black box | BenchmarkQED AutoE (assertion scores) | benchmark-qed, DeepSeek |
| 2 | Answer Relevancy | Black box | Cosine similarity embeddings вопроса и ответа | Embedding Proxy, numpy |
| 3 | Faithfulness | White box | LLM as Judge — ответ основан на контексте? | DeepSeek |
| 4 | Context Precision | White box | LLM as Judge — релевантность каждого чанка | DeepSeek |
| 5 | Context Recall | White box | LLM as Judge — покрытие ground truth | DeepSeek |
| 6 | Confidence | Black box | **ЗАГЛУШКА** — возвращает `score=1.0` | Нет |

### Confidence — заглушка

Оригинальная реализация использует UQLM (BlackBoxUQ) + LangChain + bert-score + sentence-transformers. Это тяжёлые зависимости с конфликтом numpy версий.

Заменяем на заглушку:

```python
class ConfidenceMetric:
    """Stub: UQLM removed, always returns score=1.0"""

    async def calculate_batch(self, questions: list[str]) -> list[ConfidenceResult]:
        return [ConfidenceResult(score=1.0, avg_similarity=1.0, num_responses=0) for _ in questions]
```

Убираемые зависимости: `uqlm`, `langchain`, `langchain-openai`, `langchain-model-profiles`, `bert-score`, `sentence-transformers`, `datasets`, `ipywidgets`, `optuna`, `scipy`, `scikit-learn`, `transformers`, `matplotlib`, `rich`.

### nest_asyncio и BenchmarkQED

BenchmarkQED (AutoQ и AutoE) внутри создаёт и запускает свой event loop. В основном потоке uvicorn уже работает asyncio loop, поэтому вызывать QED напрямую нельзя — будет конфликт вложенных loop'ов.

Решение — изолировать вызовы BenchmarkQED в `asyncio.to_thread()` / `run_in_executor()`. В executor-потоке нет event loop по умолчанию, поэтому QED сможет создать свой через `asyncio.new_event_loop()` без конфликтов. `nest_asyncio` при таком подходе не нужен — он патчит глобальный loop policy, что нежелательно.

```python
# В сервисе бенчмаркера:
result = await asyncio.to_thread(qed_generator.generate, documents)
```

Если QED внутри использует `asyncio.get_event_loop()` вместо `new_event_loop()` и падает — тогда в executor-потоке перед вызовом создаём loop вручную:

```python
def _run_qed_in_thread(fn, *args):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return fn(*args)
    finally:
        loop.close()

result = await asyncio.to_thread(_run_qed_in_thread, qed_generator.generate, documents)
```

Главное — основной event loop метатрона не затрагивается.

## 8. Embedding Proxy

Остаётся как отдельный сервис в docker-compose. Нужен для реализации OpenAI-совместимого интерфейса эмбеддингов, который ожидает BenchmarkQED под капотом.

Добавить в `docker-compose.yml` метатрона:

```yaml
embedding-proxy:
  build: ./embedding_proxy
  ports:
    - "8001:8001"
  environment:
    - OLLAMA_HOST=${OLLAMA_HOST:-localhost}
    - OLLAMA_PORT=${OLLAMA_PORT:-11434}
    - OLLAMA_MODEL=${OLLAMA_MODEL:-nomic-embed-text}
```

Код `embedding_proxy/` копируется из бенчмаркера в корень метатрона.

## 9. Конфигурация

Новые поля в `Settings` (`src/metatron/core/config.py`):

```python
# --- Benchmarker ---
benchmarker_embedding_proxy_url: str = Field("http://localhost:8001", alias="BENCHMARKER_EMBEDDING_PROXY_URL")
```

`documents_limit` не выносится в конфиг — передаётся с фронтенда в запросе на генерацию.

DeepSeek API key и модель уже есть в конфиге метатрона. Qdrant тоже. Дополнительные переменные не нужны.

## 10. API-эндпоинты

Все эндпоинты бенчмаркера регистрируются под `/api/v1/benchmarker/`:

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/api/v1/benchmarker/generate` | Генерация бенчмарка из документов воркспейса |
| POST | `/api/v1/benchmarker/run-tests` | Запуск тестов с 6 метриками |
| GET | `/api/v1/benchmarker/benchmarks` | Список бенчмарков воркспейса |
| GET | `/api/v1/benchmarker/benchmarks/{id}` | Бенчмарк с вопросами |
| POST | `/api/v1/benchmarker/benchmarks` | Сохранение бенчмарка |
| DELETE | `/api/v1/benchmarker/benchmarks/{id}` | Удаление бенчмарка |
| POST | `/api/v1/benchmarker/benchmarks/{id}/clone` | Клонирование бенчмарка |
| GET | `/api/v1/benchmarker/test-runs` | Список тест-ранов |
| GET | `/api/v1/benchmarker/test-runs/{id}` | Тест-ран с результатами |
| POST | `/api/v1/benchmarker/test-runs` | Создание тест-рана |
| DELETE | `/api/v1/benchmarker/test-runs/{id}` | Удаление тест-рана |

Все эндпоинты принимают `workspace_id` (query param или header) для фильтрации данных. В оригинальном бенчмаркере `workspace_id` не используется нигде — ни в API, ни в CRUD, ни в сервисах. Это значит, что адаптация затрагивает все слои: API-эндпоинты (приём параметра), CRUD-операции (фильтрация запросов), сервисы генерации и тестирования (передача workspace_id в коннекторы и chat-сервис).

Регистрация в `app.py`:

```python
from metatron.benchmarker.api import router as benchmarker_router
app.include_router(benchmarker_router, prefix="/api/v1/benchmarker")
```

Существующий `routes/benchmarker.py` (`POST /api/v1/query/trace`, 501 Not Implemented) остаётся как есть — это другой функционал, зарегистрирован на `prefix="/api/v1"`, конфликта с новым `prefix="/api/v1/benchmarker"` нет.

## 11. Зависимости

Добавить в `pyproject.toml`:

```toml
[project.optional-dependencies]
benchmarker = [
    "benchmark-qed>=0.1.0",
    "nest-asyncio>=1.5.0",
    "numpy>=1.24.0",
    "beautifulsoup4>=4.12,<5",
]
```

Уже есть в метатроне: `httpx`, `pandas`, `pydantic`, `sqlalchemy`, `fastapi`.

Не переносим (убраны вместе с UQLM): `uqlm`, `langchain`, `langchain-openai`, `langchain-model-profiles`, `bert-score`, `sentence-transformers`, `scipy`, `scikit-learn`, `transformers`, `datasets`, `ipywidgets`, `optuna`, `matplotlib`, `rich`.

## 12. Тесты

Бенчмаркер не покрыт тестами. В рамках интеграции написать тесты в стиле метатрона (pytest + pytest-asyncio):

| Модуль | Что тестировать |
|--------|----------------|
| `db/crud.py` | CRUD операции: создание/чтение/обновление/удаление бенчмарков, тест-ранов, результатов |
| `api/*.py` | API эндпоинты: валидация запросов, ответы, ошибки |
| `services/document_sampler.py` | Маппинг Document → benchmarker формат, сэмплирование |
| `services/metrics/confidence.py` | Заглушка возвращает score=1.0 |
| `schemas/*.py` | Валидация Pydantic-моделей |

Метрики и генератор (зависят от внешних API) — тестировать с моками на DeepSeek и Embedding Proxy.

Тесты размещаются в `tests/benchmarker/`.

## 13. Миграция — порядок действий

1. Создать структуру `src/metatron/benchmarker/`.
2. Перенести и адаптировать schemas (Pydantic-модели).
3. Перенести и адаптировать ORM-модели (синхронный SQLAlchemy, добавить `workspace_id`).
4. Написать миграцию `005_benchmarker.py`.
5. Написать `document_sampler.py` (адаптер коннекторов).
6. Перенести и адаптировать сервисы (generator, runner, metrics).
7. Заменить `ConfidenceMetric` на заглушку.
8. Заменить `MetatronCoreClient` на прямой вызов chat-сервиса.
9. Адаптировать `ContextFetcher` (прямой запрос в БД для query logs).
10. Перенести и адаптировать CRUD.
11. Создать API-роуты под `/api/v1/benchmarker/`.
12. Добавить конфиг-поля в `Settings`.
13. Добавить зависимости в `pyproject.toml`.
14. Скопировать `embedding_proxy/` и добавить в `docker-compose.yml`.
15. Написать тесты.
16. Проверить, что существующий функционал метатрона не затронут.

## 14. Сводка конфликтов

| Конфликт | Решение |
|----------|---------|
| Разные интерфейсы коннекторов | Адаптер `document_sampler.py` |
| Разные модели `Document` | Маппинг в адаптере |
| Sync vs async коннекторы | Вызывать async-коннекторы в async-контексте до запуска генератора |
| nest_asyncio vs uvicorn event loop | Изолировать QED-вызовы в `asyncio.to_thread()` + `new_event_loop()`, без `nest_asyncio` |
| UQLM + тяжёлые зависимости | Заглушка score=1.0 |
| Нет лимита в коннекторах | Фетч всё + сэмплирование (MVP) |
| HTTP-вызовы к самому себе | Прямые вызовы chat-сервиса + БД |
| Отдельная БД бенчмаркера | Общая БД метатрона + workspace_id |
| workspace_id отсутствует в моделях бенчмаркера | Добавить в ORM-модель, все CRUD-операции и API-эндпоинты — фильтрация по workspace_id |
