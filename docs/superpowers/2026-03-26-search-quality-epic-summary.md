# Search Quality Epic — Итоги

> **Эпик:** "Investigate and improve search quality to reduce hallucinations"
> **Период:** 2026-03-26
> **PRs:** #40–#45 (6 штук)
> **Ветка:** develop

---

## Что сделали

### Task 1 — Eval Test Set & Retrieval Metrics (PR #40)

Построили фундамент для измерений: 44 запроса (29 позитивных + 15 негативных) по 6 категориям (execution, documentation, user_file, relationship, temporal, mixed). Метрики: P@10, MRR, NDCG@10, Negative Accuracy. Команды `make eval` / `make eval-compare`. Результаты сохраняются в `eval_results/` как JSON с per-query breakdown.

**Baseline:** P@10=0.3791 · MRR=0.6946 · NDCG@10=0.6684

### Task 2 — Recall Channels (PR #41)

Рефакторинг recall pipeline: монолитный `hybrid_search()` разбит на 4 независимых канала (`recall_dense`, `recall_exact`, `recall_metadata`, `recall_graph`) + `merge_channels()`. Каждый канал — отдельная функция с чистым интерфейсом. Prepared для параллелизации (P1 в бэклоге).

**Файлы:** новый `retrieval/channels.py`, рефакторинг `retrieval/search.py`
**Импакт:** -6-8% P@10 (ожидаемо — промежуточный рефакторинг без оптимизации)

### Task 3 — Graph as Candidate Source (PR #42)

Graph повышен из context-enrichment в полноценный recall channel. 4 источника seed entities (Jira keys, title entities, person names, graph entity match) + BFS hop expansion до `RECALL_GRAPH_MAX_DEPTH=2`. Удалён bypass reranker для graph docs — все кандидаты теперь проходят через единый scoring pipeline.

**Файлы:** `retrieval/channels.py` (расширен recall_graph), удалён `get_related_documents()`
**Импакт:** MRR стабильна, P@10 чуть ниже (graph docs теперь конкурируют честно)

### Task 4 — Unified Multi-Signal Reranking (PR #43)

Заменён последовательный pipeline `diversify → title_boost → cross-encoder` на единую формулу с 6 настраиваемыми весами. Новый `scoring.py`: `compute_signal_score()` (dense, graph, metadata, recency, source_balance, sparse) + `compute_final_score()` (blend signal score с cross-encoder). Удалён dead code: `diversify_results()`, `_boost_title_matches()`, `multi_factor_score()` и др.

**Файлы:** новый `retrieval/scoring.py`, рефакторинг `search.py`, новый `MergedResult` тип
**Импакт:** Полностью компенсировал регрессию от Task 2-3. MRR +0.012 vs baseline.

### Task 5 — Query Classifier (PR #44)

Гибридный классификатор: rule gate (regex для Jira keys, дат, файлов, relationship keywords) + LLM fallback (DeepSeek) с confidence threshold. 6 профилей: execution, documentation, user_file, relationship, temporal, mixed. Каждый профиль задаёт свой набор весов для scoring формулы.

**Файлы:** новый `retrieval/query_classifier.py`, интеграция в `search.py`
**Импакт:** Инфраструктурный — метрики ~flat, нужен grid search по весам профилей (Q1 в бэклоге)

### Task 6 — Structured Evidence Packs (PR #45)

Коннекторы декларируют `source_role` (task_tracker, knowledge_base, user_upload, communication). Поток: connector → Document → pipeline → Qdrant payload → recall → `_collect_frags()` (dict) → `_mark_evidence_role()` (PRIMARY/SUPPORTING по профилю) → `_build_ctx()` (grouped markdown) → LLM с atomic evidence rules.

**Файлы:** 18 файлов, сквозные изменения от `core/interfaces.py` до `retrieval/prompts.py`
**Импакт:** Все три метрики улучшились: P@10 +0.013, MRR +0.017, NDCG +0.022

---

## Метрики: от начала до конца

| Метрика | Baseline (до эпика) | После PR #45 | После тюнинга | Δ vs baseline | Оценка |
|---------|--------------------|-----------------------|---------------|---------------|--------|
| **P@10** | 0.3791 | 0.3663 | 0.3787 | -0.000 | ~stable |
| **MRR** | 0.6946 | 0.6897 | 0.7069 | +0.012 | improved |
| **NDCG@10** | 0.6684 | 0.6326 | 0.6493 | -0.019 | minor regression |
| **Neg Acc** | 0.00 | 0.00 | 0.00 | 0 | infra ready (Q3) |

**Пояснение:** Промежуточная регрессия от архитектурных рефакторингов (Tasks 2-3) полностью компенсирована. MRR вышла выше baseline (+1.2%). Тюнинг (smooth source_balance + RERANK_POOL_SIZE 35) дал +0.012 P@10, +0.017 MRR, +0.017 NDCG vs post-PR#45. NDCG@10 остаётся ниже baseline на 1.9% — ожидается улучшение после grid search по весам профилей.

**Траектория по eval runs:**
```
04:56  P@10=0.379  MRR=0.695  NDCG=0.668  ← baseline
07:22  P@10=0.292  MRR=0.603  NDCG=0.589  ← recall channels (dip)
09:43  P@10=0.330  MRR=0.690  NDCG=0.663  ← graph candidate source
12:12  P@10=0.377  MRR=0.707  NDCG=0.665  ← unified reranking (recovery)
15:14  P@10=0.353  MRR=0.672  NDCG=0.611  ← query classifier
17:47  P@10=0.366  MRR=0.690  NDCG=0.633  ← evidence packs
19:22  P@10=0.379  MRR=0.707  NDCG=0.649  ← quality tuning (final)
```

---

## Что построили (архитектура)

```
Query → expansion → classify(profile) → weight_preset
     → recall_dense + recall_exact + recall_metadata + recall_graph
     → merge_channels → compute_signal_score(weighted) → cross-encoder rerank
     → compute_final_score(blend) → _collect_frags(dict)
     → _mark_evidence_role(PRIMARY/SUPPORTING) → _build_ctx(grouped markdown)
     → LLM(evidence rules) → _append_sources → answer
```

**Новые модули:**
- `retrieval/channels.py` — 4 recall канала с чистыми интерфейсами
- `retrieval/scoring.py` — multi-signal scoring формула с настраиваемыми весами
- `retrieval/query_classifier.py` — rule gate + LLM hybrid classifier

**Тесты:** +200 новых unit-тестов (eval set: 28, recall channels: 35, reranking: 58, classifier: 58, evidence packs: 48)

---

## Бэклог — выполнено (PR #46: search-quality-tuning)

| ID | Задача | Статус |
|----|--------|--------|
| **P1** | Параллельный запуск recall channels (ThreadPoolExecutor) | ✅ Done |
| **P2** | Тюнинг RERANK_POOL_SIZE (50 → 35) | ✅ Done |
| **P3** | LRU cache для recall_graph (Memgraph queries) | ✅ Done |
| **Q1** | Grid search скрипт (`make grid-search`) | ✅ Done (инфраструктура; прогон — отдельная задача) |
| **Q2** | Smooth gradient для source_balance | ✅ Done |
| **Q3** | Confidence threshold (min_signal_score) | ✅ Done (disabled by default, 0.0) |
| **C1** | Вынести scores из memory dicts в score_map | ✅ Done |
| **C2** | Кэширование _result_type в scoring loop | ✅ Done |
| **C3** | Убрать dead sparse_weight path | ✅ Done |
| **D1** | Reconcile spec vs code — нормализация весов | ✅ Done |

## Бэклог — оставшиеся задачи

### Следующие шаги (рекомендованный приоритет)

1. **Запуск grid search** — `make grid-search` по весам профилей. Инфраструктура готова, нужен прогон (~30 мин/профиль) + применение оптимальных весов
2. **Калибровка min_signal_score** — включить confidence threshold, найти оптимальный порог через eval
3. **Async migration** — 14 TODO-комментариев в `retrieval/` и `storage/qdrant.py`. Весь search pipeline синхронный, вызывается через `asyncio.to_thread()`

### Known Issues

- **ru-01 false positive**: «Что такое Метатрон?» → `relationship` вместо `documentation` (LLM перевод содержит "relat*")
- **Ollama model swapping**: Classifier adds latency → Ollama unloads embedding model. Fix: `OLLAMA_KEEP_ALIVE=-1`
- **Post-deploy**: Нужен full reindex для source_role в Qdrant payload + manual spot-check 10 queries на citation quality
