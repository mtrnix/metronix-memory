# Search Quality Epic — Backlog

> Доработки и улучшения, выявленные в ходе реализации эпика
> "Investigate and improve search quality to reduce hallucinations".

---

## Выполнено (PR #46: feature/search-quality-tuning)

| ID | Задача | Решение |
|----|--------|---------|
| **P1** | Параллельный запуск recall channels | `ThreadPoolExecutor(max_workers=4)` в search.py |
| **P2** | Уменьшить RERANK_POOL_SIZE | 50 → 35, eval подтвердил: без регрессии |
| **P3** | Кэширование recall_graph | `@lru_cache(maxsize=128)` на `_cached_get_graph_entities` |
| **Q1** | Grid search по весам | Скрипт `scripts/grid_search_weights.py`, `make grid-search` |
| **Q2** | Smooth gradient для source_balance | Линейный decay `1.0 - (ratio / threshold)` |
| **Q3** | Confidence threshold | `min_signal_score` в config (default 0.0 = disabled) |
| **C1** | Score leak в memory dicts | `score_map: dict[str, float]` по chunk_id |
| **C2** | Кэширование _result_type | `type_cache` dict в scoring loop |
| **C3** | Dead sparse_weight path | Удалён из scoring.py и query_classifier.py |
| **D1** | Spec vs code — нормализация | Спека обновлена: делится на сумму ВСЕХ весов |

**Eval результат:** P@10=0.379 (+0.012), MRR=0.707 (+0.017), NDCG=0.649 (+0.017) vs pre-tuning.

---

## Оставшиеся задачи

### 1. Grid search — переписать на scoring-only (приоритет: высокий)

**Проблема:** Текущий скрипт (`make grid-search`) прогоняет полный search pipeline на каждую комбинацию весов — recall, reranker, LLM. При 1125 комбинаций × 29 запросов × ~25 сек/запрос × 6 профилей = **месяцы** работы. Нереально.

**Решение:** Переписать на двухфазный подход:
1. **Фаза 1 (один раз):** прогнать recall + reranker на всех 29 запросах, сохранить `channel_scores` и `rerank_score` для каждого кандидата в JSON-кэш
2. **Фаза 2 (мгновенно):** перебирать комбинации весов, пересчитывая только `compute_signal_score()` + `compute_final_score()` из кэшированных scores. Чистая арифметика — ~1000x быстрее

Фаза 1 ≈ 12 мин (один прогон eval). Фаза 2 ≈ секунды на все 6750 комбинаций.

**Как запустить (когда скрипт будет переписан):**
```bash
make grid-search-cache    # фаза 1: кэшировать recall+rerank (12 мин)
make grid-search           # фаза 2: перебрать веса (секунды)
```

### 2. Калибровка min_signal_score (приоритет: средний)
Threshold disabled by default. Нужен eval для подбора порога → включить → замерить Negative Accuracy (сейчас 0%).

### 3. Инвалидация graph entity cache после sync (приоритет: средний)
`_cached_get_graph_entities` в `channels.py` — LRU cache без TTL (maxsize=128). После sync в Memgraph кэш содержит stale данные до LRU eviction. Нужно: подписаться на `SYNC_COMPLETED` event и вызвать `cache_clear()`. Prerequisite: EventBus должен emit'ить `SYNC_COMPLETED` (сейчас event определён, но не emit'ится нигде).

### 4. Async migration (приоритет: низкий, tech debt)
14 TODO-комментариев `# TODO: async migration` в `retrieval/` и `storage/qdrant.py`. Весь search pipeline синхронный, вызывается через `asyncio.to_thread()`. P1 обошёл это через ThreadPoolExecutor.

---

## Known Issues

- **Graph cache staleness**: `_cached_get_graph_entities` (LRU, no TTL) — stale после sync. При текущей частоте sync (раз в несколько часов) и размере кэша (128) — практически не влияет. Будет решено после подключения EventBus к sync lifecycle
- **ru-01 false positive**: «Что такое Метатрон?» → `relationship` вместо `documentation` (LLM перевод содержит "relat*")
- **Ollama model swapping**: Classifier adds latency → Ollama unloads embedding model. Fix: `OLLAMA_KEEP_ALIVE=-1`
- **Post-deploy**: Нужен full reindex для source_role в Qdrant payload + manual spot-check 10 queries

---

## Query Classifier — Known Gaps

Классификатор в текущем виде не улучшает метрики (MRR -0.035, NDCG -0.045 vs baseline). Оставлен включённым как инфраструктура. Ожидается улучшение после grid search по весам профилей.
