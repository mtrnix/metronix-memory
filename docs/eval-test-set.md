# Eval Test Set — Search Quality Measurement

## What is this

A developer tool for measuring retrieval quality before and after pipeline changes.
Not a product feature. The system consists of:

- A YAML test set with 16 labeled queries and ground-truth `doc_labels`
- Three deterministic retrieval metrics (no LLM calls): Precision@K, MRR, NDCG@K
- Extended pipeline trace from `hybrid_search_and_answer(return_trace=True)`

Use it whenever you change anything in the search pipeline (reranker tuning, scoring
weights, query expansion logic, diversification, etc.) to verify you did not regress.

## Quick Start

Требуется запущенный Metatron с Ollama, Qdrant и проиндексированными данными воркспейса.

```bash
# Запуск с дефолтным воркспейсом MTRNIX
make eval

# Указать конкретный воркспейс
make eval WORKSPACE=my_workspace

# Сохранить результаты для дальнейшего сравнения
make eval-save

# Прогнать и сравнить с последним сохранённым результатом
make eval-compare

# Посмотреть историю всех сохранённых прогонов
make eval-history

# Или напрямую с доп. опциями
python scripts/run_eval.py --workspace MTRNIX --k 5 --testset path/to/custom.yaml
python scripts/run_eval.py --compare eval_results/2026-03-25T14-30-00.json
```

Юнит-тесты метрик (без внешних зависимостей, ~1 сек):

```bash
pytest tests/unit/test_retrieval_metrics.py tests/unit/test_eval_testset_loader.py tests/unit/test_benchmarker_retrieval_integration.py -v
```

## Programmatic Usage

```python
from metatron.retrieval.search import hybrid_search_and_answer
from metatron.benchmarker.services.metrics.retrieval import RetrievalMetrics
from metatron.benchmarker.services.eval_loader import load_eval_testset_from_path, DEFAULT_TESTSET_PATH

ts = load_eval_testset_from_path(DEFAULT_TESTSET_PATH)
rm = RetrievalMetrics()

pairs = []
for q in ts.queries:
    trace = hybrid_search_and_answer(q.text, 'MTRNIX', 10, None, None, return_trace=True)
    retrieved = trace.get('retrieved_doc_labels', []) if isinstance(trace, dict) else []
    result = rm.compute(retrieved, q.expected_doc_labels, k=10)
    pairs.append((retrieved, q.expected_doc_labels))
    print(f'[{q.id}] P@10={result["precision_at_k"]:.2f} MRR={result["mrr"]:.2f} NDCG@10={result["ndcg_at_k"]:.2f}')

avgs = rm.compute_averages(pairs, k=10)
print(f'Avg P@10={avgs["avg_precision_at_k"]:.4f}  Avg MRR={avgs["avg_mrr"]:.4f}  Avg NDCG@10={avgs["avg_ndcg_at_k"]:.4f}')
```

## Metrics Explained

All three metrics are deterministic (pure math, no LLM). They compare the ordered list of
`retrieved_doc_labels` against the ground-truth `expected_doc_labels`.

| Metric | Question it answers | Range | Higher is better |
|--------|-------------------|-------|-----------------|
| **Precision@10** | Of the top 10 results, what fraction are actually relevant? | 0.0 -- 1.0 | Yes |
| **MRR** | How quickly does the first relevant result appear? (1/rank) | 0.0 -- 1.0 | Yes |
| **NDCG@10** | Are the relevant results ranked near the top? (position-weighted) | 0.0 -- 1.0 | Yes |

Details:

- **Precision@10**: `relevant_in_top_10 / 10`. A score of 0.30 means 3 out of 10 results
  were relevant. Low P@10 with high MRR means the system finds the right docs but also
  returns noise/duplicates.

- **MRR (Mean Reciprocal Rank)**: `1 / rank_of_first_relevant`. If the first relevant doc
  is at position 1, MRR = 1.0. At position 3, MRR = 0.33. Measures how fast the user sees
  something useful.

- **NDCG@10 (Normalized Discounted Cumulative Gain)**: Uses binary relevance with
  logarithmic discount. Rewards having relevant docs ranked higher. A perfect NDCG means
  all relevant docs are at the very top positions.

The `RetrievalMetrics.compute()` method deduplicates `retrieved_doc_labels` before computing,
so repeated labels from multiple chunks of the same document do not inflate scores.

## Test Set Structure

Location: `src/metatron/benchmarker/fixtures/search_quality_testset.yaml`

```yaml
version: "1.0"
description: >
  Search quality evaluation test set for MTRNIX workspace.
  16 queries across 5 intent categories with ground-truth doc_labels.

queries:
  - id: "exec-01"
    text: "What is the status of MTRNIX-104?"
    category: "execution/status-heavy"
    expected_doc_labels:
      - "MTRNIX-104"
    notes: "Direct Jira key lookup -- RBAC implementation ticket"
```

Fields:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier, prefixed by category: `exec-`, `doc-`, `file-`, `rel-`, `mix-` |
| `text` | Yes | The search query as a user would type it |
| `expected_doc_labels` | Yes | Set of `doc_label` values that should appear in results |
| `category` | No | Intent category (defaults to `"mixed"`) |
| `notes` | No | Human-readable explanation of what the query tests |

### Categories (5)

| Category | Primary source | Example query |
|----------|---------------|---------------|
| `execution/status-heavy` | Jira tickets | "What tasks are currently in progress?" |
| `documentation-heavy` | Confluence pages | "What are the coding standards?" |
| `user-file-heavy` | Uploaded files | "What does the Adobe 10K report say about revenue?" |
| `relationship-heavy` | Graph relationships | "How does RBAC relate to user-ingested documents?" |
| `mixed` | Multiple sources | "What is the RBAC implementation plan for Metatron?" |

### What are doc_labels?

A `doc_label` is a string stored in the Qdrant payload for every chunk. It identifies the
source document:

- Jira tickets: `"MTRNIX-104"`
- Confluence pages: `"285343747"` (page ID)
- Uploaded files: `"MTRNIX:user:ADOBE_2016_10K.pdf:2026-03-05T06:10:57.319819+00:00"`
- Other uploads: `"upload:test_upload.txt"`

## How to Update the Test Set

### When to add queries

- You added a new connector or source type
- You changed scoring/ranking logic and need coverage for the affected query pattern
- A user reported a bad search result and you want to prevent regression

### How to find doc_labels for a new query

Run the query with `return_trace=True` and inspect what comes back:

```python
trace = hybrid_search_and_answer("your query here", 'eval', 10, None, None, return_trace=True)
for label in trace['retrieved_doc_labels']:
    print(label)
```

### Steps

1. Run the query and inspect `retrieved_doc_labels` to see what labels exist in the index
2. Decide which of those labels are genuinely relevant (ground truth)
3. Add a new entry to the YAML file with a unique `id` following the naming convention
4. Set `expected_doc_labels` to the labels that SHOULD be returned (not what IS returned)
5. Choose the appropriate `category`
6. Run the eval to see where the new query lands

### Validation

The loader (`eval_loader.py`) enforces:
- At least 1 query in the test set
- No duplicate query IDs
- Every query must have `id`, `text`, and `expected_doc_labels`

## Pipeline Trace Fields

When you call `hybrid_search_and_answer(..., return_trace=True)`, the return value is a dict
instead of a string. The trace contains:

```python
{
    "answer": "...",              # Final LLM answer with sources appended
    "source_results": [...],      # List of result dicts from Qdrant
    "fragments": [...],           # Text fragments sent to LLM context
    "graph_entities": [...],      # Entities from Memgraph
    "graph_relations": [...],     # Relationships from Memgraph
    "graph_docs": [...],          # Related documents from graph traversal
    "retrieved_doc_labels": [...], # Ordered doc_labels from source_results
    "pipeline_stages": {
        "original_query": "...",         # Raw user query
        "translated_query": "...",       # English translation (if Cyrillic input)
        "expanded_query": "...",         # LLM-expanded query
        "detected_language": "en",       # "en" or "ru"
        "pre_rerank_count": 75,          # Candidates before reranker
        "post_rerank_count": 25,         # Results after reranker
        "pre_diversify_count": 50,       # Results before diversification
        "post_diversify_count": 50,      # Results after diversification
        "fragment_count": 12,            # Fragments sent to LLM
        "token_budget_used": 3200,       # Approximate tokens used
    },
}
```

Use `pipeline_stages` to debug where a query goes wrong:

- **Query not finding results?** Check `translated_query` and `expanded_query` -- the
  expansion may be drifting from the original intent.
- **Right docs retrieved but ranked low?** Compare `pre_rerank_count` vs `post_rerank_count`
  -- the reranker may be dropping relevant results.
- **Too much noise?** Check `pre_diversify_count` vs `post_diversify_count` -- diversification
  should reduce duplicates from the same source.
- **Context too short/long?** Check `fragment_count` and `token_budget_used`.

## Baseline (2026-03-25)

Measured on the MTRNIX workspace with 16 queries, k=10.

### Overall

| Metric | Score |
|--------|-------|
| Avg Precision@10 | 0.4861 |
| Avg MRR | 0.9688 |
| Avg NDCG@10 | 0.9636 |

### Per-Category Breakdown

| Category | Queries | Avg P@10 | Avg MRR | Avg NDCG@10 |
|----------|---------|----------|---------|-------------|
| execution/status-heavy | 3 | exec-01, exec-02, exec-03 | -- | -- |
| documentation-heavy | 3 | doc-01, doc-02, doc-03 | -- | -- |
| user-file-heavy | 3 | file-01, file-02, file-03 | -- | -- |
| relationship-heavy | 3 | rel-01, rel-02, rel-03 | -- | -- |
| mixed | 4 | mix-01, mix-02, mix-03, mix-04 | -- | -- |

(Per-category breakdowns should be filled in after running the eval per category.)

### Interpretation

- **MRR = 0.97**: The system almost always places a relevant document at position 1.
  Users see a useful result immediately.
- **NDCG@10 = 0.96**: When multiple relevant docs exist, they are ranked near the top.
  The ranking quality is strong.
- **P@10 = 0.49**: Only about half of the top-10 results are relevant. The rest is noise
  -- typically duplicate chunks from the same document, or tangentially related pages.
  This is the main area for improvement (better deduplication, stricter relevance
  thresholds, or reducing pool size).

## Before/After Workflow

Step by step process for evaluating a pipeline change:

### 1. Save baseline

```bash
make eval-save
```

Результаты сохраняются в `eval_results/<timestamp>.json` с полным снепшотом:
per-query метрики, retrieved/expected doc_labels, средние по всем запросам.

### 2. Make pipeline changes

Edit the relevant files in `src/metatron/retrieval/`.

### 3. Compare

```bash
make eval-compare
```

Вывод покажет таблицу BEFORE / NOW / DELTA по каждой метрике и список
конкретных запросов, на которых произошла регрессия или улучшение:

```
              BEFORE       NOW          DELTA
P@K           0.4861     0.5500      +0.0639  +
MRR           0.9688     0.9688       0.0000
NDCG@K        0.9636     0.9800      +0.0164  +

Regressions (1):
  [exec-02 ] MRR  1.00 -> 0.50

Improvements (3):
  [doc-01  ] P@K  0.10 -> 0.30
  [file-02 ] P@K  0.00 -> 0.20
  [mix-01  ] NDCG@K  0.75 -> 0.90
```

Можно также сравнить с конкретным прогоном:

```bash
python scripts/run_eval.py --compare eval_results/2026-03-25T14-30-00.json
```

### 4. History

```bash
make eval-history
```

Показывает все сохранённые прогоны с метриками для отслеживания тренда.

### 5. Interpret

- **MRR drop**: You broke first-result quality. Likely a ranking or boosting change.
- **NDCG drop**: Relevant docs are being pushed down. Check reranker or diversification.
- **P@10 drop**: More noise in top 10. Check pool size or deduplication.
- **P@10 improvement without MRR/NDCG drop**: Good -- you reduced noise without hurting ranking.

### 5. Investigate regressions with pipeline trace

If a specific query regressed, inspect its trace:

```python
trace = hybrid_search_and_answer("the failing query", 'eval', 10, None, None, return_trace=True)
stages = trace['pipeline_stages']
print(f"Original:  {stages['original_query']}")
print(f"Expanded:  {stages['expanded_query']}")
print(f"Pre-rerank:  {stages['pre_rerank_count']}")
print(f"Post-rerank: {stages['post_rerank_count']}")
print(f"Fragments:   {stages['fragment_count']}")

# Check what doc_labels were retrieved vs expected
print(f"Retrieved: {trace['retrieved_doc_labels']}")
```
