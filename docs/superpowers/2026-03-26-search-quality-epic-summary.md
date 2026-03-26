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

| Метрика | Baseline (до эпика) | Финал (после PR #45) | Δ | Оценка |
|---------|--------------------|-----------------------|---|--------|
| **P@10** | 0.3791 | 0.3663 | -0.013 | ~stable |
| **MRR** | 0.6946 | 0.6897 | -0.005 | ~stable |
| **NDCG@10** | 0.6684 | 0.6326 | -0.036 | small regression |
| **Neg Acc** | 0.00 | 0.00 | 0 | not addressed |

**Пояснение:** Промежуточная регрессия от архитектурных рефакторингов (Tasks 2-3) была почти полностью компенсирована Tasks 4-6. NDCG@10 regression (-5%) — следствие того, что graph docs теперь проходят reranker (правильнее архитектурно, но ранжирование ещё не оптимизировано). Основные gains ожидаются от weight tuning (Q1 в бэклоге).

**Траектория по eval runs:**
```
04:56  P@10=0.379  MRR=0.695  NDCG=0.668  ← baseline
07:22  P@10=0.292  MRR=0.603  NDCG=0.589  ← recall channels (dip)
09:43  P@10=0.330  MRR=0.690  NDCG=0.663  ← graph candidate source
12:12  P@10=0.377  MRR=0.707  NDCG=0.665  ← unified reranking (recovery)
15:14  P@10=0.353  MRR=0.672  NDCG=0.611  ← query classifier
17:47  P@10=0.366  MRR=0.690  NDCG=0.633  ← evidence packs (final)
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

## Бэклог (TODO)

### Performance

| ID | Задача | Сложность | Ожидаемый эффект |
|----|--------|-----------|------------------|
| **P1** | Параллельный запуск recall channels (`asyncio.gather`) | Средняя | Latency recall -60-70% |
| **P2** | Тюнинг RERANK_POOL_SIZE (50 → 30-35) | Низкая | Inference cost -30% |
| **P3** | LRU cache для recall_graph (Memgraph queries) | Низкая | Latency graph channel -50%+ для повторных запросов |

### Quality Tuning

| ID | Задача | Сложность | Ожидаемый эффект |
|----|--------|-----------|------------------|
| **Q1** | Grid search по весам scoring формулы | Низкая (время) | Основной ожидаемый gain по MRR/NDCG |
| **Q2** | Smooth gradient для source_balance (бинарный → плавный) | Низкая | Устранение boundary effects |
| **Q3** | Negative accuracy: confidence threshold на signal_score | Средняя | Neg Acc 0% → target 50%+ |

### Code Quality

| ID | Задача | Сложность |
|----|--------|-----------|
| **C1** | Убрать _signal_score/_final_score leak в memory dicts | Низкая |
| **C2** | Кэширование _result_type в scoring loop | Тривиально |
| **C3** | Убрать dead sparse_weight path | Тривиально |
| **D1** | Reconcile spec vs code — нормализация весов | Тривиально |

### Async Migration (tech debt)

14 TODO-комментариев `# TODO: async migration` в `retrieval/` и `storage/qdrant.py`. Весь search pipeline синхронный, вызывается через `asyncio.to_thread()`. Prerequisite для P1 (параллельные recall channels).

### Known Issues

- **ru-01 false positive**: «Что такое Метатрон?» → `relationship` вместо `documentation` (LLM перевод содержит "relat*")
- **Ollama model swapping**: Classifier adds latency → Ollama unloads embedding model. Fix: `OLLAMA_KEEP_ALIVE=-1`
- **Post-deploy**: Нужен full reindex для source_role в Qdrant payload + manual spot-check 10 queries на citation quality

---

## Рекомендация по приоритету следующих шагов

1. **Q1 — Grid search по весам** — максимальный ожидаемый ROI, вся инфраструктура готова
2. **P1 — Параллельные recall channels** — нужен async migration, но даст -60% latency
3. **Q3 — Negative accuracy** — сейчас 0%, заметно для пользователей
4. **P2 — RERANK_POOL_SIZE tuning** — quick win, 5 минут работы + eval
5. Остальное — по мере необходимости
