# Query Classifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify incoming queries into 6 intent profiles and dynamically adjust scoring weights so the most relevant recall channel and signal dominate the ranking.

**Architecture:** Hybrid classifier — fast rule gate covers obvious cases (Jira keys, dates, keywords), LLM fallback for ambiguous queries. Each profile maps to a weight preset applied to `compute_signal_score()` and `compute_final_score()`. Graceful degradation: any failure → `mixed` profile (current defaults, zero behavior change).

**Tech Stack:** Python 3.12, regex (rule gate), `chat_completion` from `metatron.llm` (LLM fallback), pydantic-settings (config)

**Spec:** `docs/superpowers/specs/2026-03-26-query-classifier-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `src/metatron/core/config.py` | Modify | Add `query_classifier_enabled` field to Settings |
| `src/metatron/retrieval/query_classifier.py` | Create | Rule gate, LLM fallback, `classify_query()`, `get_profile_weights()`, weight presets, `QueryClassification` TypedDict |
| `src/metatron/retrieval/search.py` | Modify | Call `classify_query()`, pass profile weights to scoring loop, add trace fields |
| `tests/unit/test_query_classifier.py` | Create | All tests for query classifier |
| `tests/unit/test_search_trace_extended.py` | Modify | Add `classify_query` patch to `_patch_search_internals()`, verify new trace fields |

---

### Task 1: Add `query_classifier_enabled` config field

**Files:**
- Modify: `src/metatron/core/config.py:109` (after `reranker_enabled`)
- Test: `tests/unit/test_query_classifier.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_query_classifier.py`:

```python
"""Tests for query classifier: config, rule gate, LLM fallback, integration."""

from __future__ import annotations


class TestQueryClassifierConfig:
    def test_query_classifier_enabled_default_true(self) -> None:
        from metatron.core.config import Settings

        s = Settings()
        assert s.query_classifier_enabled is True

    def test_query_classifier_disabled_via_env(self, monkeypatch) -> None:
        from metatron.core.config import Settings

        monkeypatch.setenv("QUERY_CLASSIFIER_ENABLED", "false")
        s = Settings()
        assert s.query_classifier_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_query_classifier.py::TestQueryClassifierConfig -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'query_classifier_enabled'`

- [ ] **Step 3: Add config field**

In `src/metatron/core/config.py`, after line 109 (`reranker_enabled`), add:

```python
    query_classifier_enabled: bool = Field(True, alias="QUERY_CLASSIFIER_ENABLED")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_query_classifier.py::TestQueryClassifierConfig -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/metatron/core/config.py tests/unit/test_query_classifier.py
git commit -m "feat(classifier): add query_classifier_enabled config field"
```

---

### Task 2: Weight presets and `get_profile_weights()`

**Files:**
- Create: `src/metatron/retrieval/query_classifier.py`
- Test: `tests/unit/test_query_classifier.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_query_classifier.py`:

```python
import pytest


class TestProfileWeights:
    def test_all_profiles_exist(self) -> None:
        from metatron.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS

        expected = {"execution", "documentation", "user_file", "relationship", "temporal", "mixed"}
        assert set(QUERY_PROFILE_WEIGHTS.keys()) == expected

    @pytest.mark.parametrize("profile", [
        "execution", "documentation", "user_file", "relationship", "temporal", "mixed",
    ])
    def test_signal_weights_sum_to_085(self, profile: str) -> None:
        from metatron.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS

        w = QUERY_PROFILE_WEIGHTS[profile]
        signal_sum = (
            w["dense_weight"] + w["sparse_weight"] + w["graph_weight"]
            + w["metadata_weight"] + w["recency_weight"] + w["balance_weight"]
        )
        assert abs(signal_sum - 0.85) < 1e-9, f"{profile}: signal sum = {signal_sum}"

    @pytest.mark.parametrize("profile", [
        "execution", "documentation", "user_file", "relationship", "temporal", "mixed",
    ])
    def test_all_weight_keys_present(self, profile: str) -> None:
        from metatron.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS

        expected_keys = {
            "dense_weight", "sparse_weight", "graph_weight",
            "metadata_weight", "recency_weight", "balance_weight", "blend_weight",
        }
        assert set(QUERY_PROFILE_WEIGHTS[profile].keys()) == expected_keys

    def test_mixed_matches_current_defaults(self) -> None:
        """mixed profile must match compute_signal_score() defaults exactly."""
        from metatron.retrieval.query_classifier import QUERY_PROFILE_WEIGHTS

        mixed = QUERY_PROFILE_WEIGHTS["mixed"]
        assert mixed["dense_weight"] == 0.35
        assert mixed["sparse_weight"] == 0.0
        assert mixed["graph_weight"] == 0.15
        assert mixed["metadata_weight"] == 0.20
        assert mixed["recency_weight"] == 0.10
        assert mixed["balance_weight"] == 0.05
        assert mixed["blend_weight"] == 0.30

    def test_get_profile_weights_valid(self) -> None:
        from metatron.retrieval.query_classifier import get_profile_weights

        w = get_profile_weights("execution")
        assert w["dense_weight"] == 0.20
        assert w["metadata_weight"] == 0.35

    def test_get_profile_weights_unknown_falls_back_to_mixed(self) -> None:
        from metatron.retrieval.query_classifier import get_profile_weights

        w = get_profile_weights("nonexistent")
        assert w == get_profile_weights("mixed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_query_classifier.py::TestProfileWeights -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'metatron.retrieval.query_classifier'`

- [ ] **Step 3: Create `query_classifier.py` with weight presets**

Create `src/metatron/retrieval/query_classifier.py`:

```python
"""Query classifier for source-of-truth profiles.

Classifies incoming queries into 6 intent profiles and returns weight
presets for compute_signal_score() and compute_final_score().

Hybrid approach: fast rule gate for obvious cases, LLM fallback for ambiguous.
Any failure gracefully degrades to 'mixed' (current defaults).
"""

from __future__ import annotations

from typing import TypedDict

import structlog

logger = structlog.get_logger()


class QueryClassification(TypedDict):
    profile: str       # "execution" | "documentation" | "user_file" | "relationship" | "temporal" | "mixed"
    confidence: float  # 0.0 - 1.0
    method: str        # "rule" | "llm" | "default" | "disabled"


QUERY_PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "execution":     {"dense_weight": 0.20, "sparse_weight": 0.0, "graph_weight": 0.10, "metadata_weight": 0.35, "recency_weight": 0.15, "balance_weight": 0.05, "blend_weight": 0.25},
    "documentation": {"dense_weight": 0.45, "sparse_weight": 0.0, "graph_weight": 0.15, "metadata_weight": 0.15, "recency_weight": 0.05, "balance_weight": 0.05, "blend_weight": 0.35},
    "user_file":     {"dense_weight": 0.45, "sparse_weight": 0.0, "graph_weight": 0.05, "metadata_weight": 0.20, "recency_weight": 0.05, "balance_weight": 0.10, "blend_weight": 0.35},
    "relationship":  {"dense_weight": 0.25, "sparse_weight": 0.0, "graph_weight": 0.35, "metadata_weight": 0.15, "recency_weight": 0.05, "balance_weight": 0.05, "blend_weight": 0.25},
    "temporal":      {"dense_weight": 0.25, "sparse_weight": 0.0, "graph_weight": 0.10, "metadata_weight": 0.15, "recency_weight": 0.30, "balance_weight": 0.05, "blend_weight": 0.30},
    "mixed":         {"dense_weight": 0.35, "sparse_weight": 0.0, "graph_weight": 0.15, "metadata_weight": 0.20, "recency_weight": 0.10, "balance_weight": 0.05, "blend_weight": 0.30},
}


def get_profile_weights(profile: str) -> dict[str, float]:
    """Return weight preset for the given profile. Falls back to 'mixed' if unknown."""
    return QUERY_PROFILE_WEIGHTS.get(profile, QUERY_PROFILE_WEIGHTS["mixed"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_query_classifier.py::TestProfileWeights -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/metatron/retrieval/query_classifier.py tests/unit/test_query_classifier.py
git commit -m "feat(classifier): add weight presets and get_profile_weights()"
```

---

### Task 3: Rule gate

**Files:**
- Modify: `src/metatron/retrieval/query_classifier.py`
- Test: `tests/unit/test_query_classifier.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_query_classifier.py`:

```python
class TestRuleGate:
    """Rule gate classifies obvious cases without LLM."""

    # -- execution profile --
    def test_jira_key_triggers_execution(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What is the status of MTRNIX-104?") == "execution"

    def test_jira_key_case_insensitive(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("mtrnix-104") == "execution"

    def test_status_keyword_triggers_execution(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What tasks are in progress?") == "execution"

    def test_russian_status_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Что в работе?") == "execution"

    def test_sprint_keyword_triggers_execution(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What is in the current sprint?") == "execution"

    def test_backlog_keyword_triggers_execution(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Show me the backlog") == "execution"

    # -- temporal profile --
    def test_date_expression_triggers_temporal(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What was done last week?") == "temporal"

    def test_this_month_triggers_temporal(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Show changes this month") == "temporal"

    def test_recently_triggers_temporal(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What was updated recently?") == "temporal"

    def test_russian_temporal_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Что было на этой неделе?") == "temporal"

    # -- user_file profile --
    def test_uploaded_triggers_user_file(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What does the uploaded document say?") == "user_file"

    def test_pdf_triggers_user_file(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Summarize the PDF report") == "user_file"

    def test_10k_triggers_user_file(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What does the 10K say?") == "user_file"

    def test_russian_file_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Что в загруженном файле?") == "user_file"

    def test_russian_file_word_forms(self) -> None:
        """файл prefix should match all word forms: файлы, файла, файле."""
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Покажи файлы") == "user_file"
        assert _rule_gate("Содержание файла") == "user_file"

    # -- relationship profile --
    def test_relationship_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("How does RBAC relate to auth?") == "relationship"

    def test_depends_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What depends on the auth module?") == "relationship"

    def test_between_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What is the link between RBAC and users?") == "relationship"

    def test_russian_relationship_keyword(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("Как связаны RBAC и пользователи?") == "relationship"

    # -- no match / ambiguous --
    def test_no_match_returns_none(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        assert _rule_gate("What is Metatron?") is None

    def test_multiple_profiles_returns_none(self) -> None:
        """Query matching 2+ profiles should fall through to LLM."""
        from metatron.retrieval.query_classifier import _rule_gate

        # "in progress" → execution, "last week" → temporal
        assert _rule_gate("What was in progress last week?") is None

    # -- word boundary safety --
    def test_file_word_boundary(self) -> None:
        """'profile' should NOT match \\bfile\\b."""
        from metatron.retrieval.query_classifier import _rule_gate

        # Should not match user_file just because "profile" contains "file"
        result = _rule_gate("Update the user profile settings")
        assert result != "user_file"

    def test_between_word_boundary(self) -> None:
        from metatron.retrieval.query_classifier import _rule_gate

        # "between" as standalone word triggers relationship
        assert _rule_gate("difference between A and B") == "relationship"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_query_classifier.py::TestRuleGate -v`
Expected: FAIL — `ImportError: cannot import name '_rule_gate'`

- [ ] **Step 3: Implement rule gate**

Add to `src/metatron/retrieval/query_classifier.py`, after the `get_profile_weights` function:

```python
import re

from metatron.ingestion.processors.dates import extract_date_range

# -- Rule gate patterns (per profile) --

_JIRA_KEY_RE = re.compile(r'\b[A-Z]{2,}-\d+\b', re.IGNORECASE)

_EXECUTION_KW = re.compile(
    r'\bin progress\b|\bdone\b|\bsprint\b|\bbacklog\b'
    r'|\bв работе\b|\bтекущий спринт\b',
    re.IGNORECASE,
)

_TEMPORAL_KW = re.compile(
    r'\bthis month\b|\blast week\b|\blast month\b|\brecently\b|\bthis week\b'
    r'|\bна этой неделе\b|\bза последний месяц\b|\bна прошлой неделе\b|\bнедавно\b',
    re.IGNORECASE,
)

_USER_FILE_KW = re.compile(
    r'\bfile\b|\buploaded\b|\bpdf\b|\breport\b|\b10K\b'
    r'|\bфайл|\bзагруженн|\bотчет\b',
    re.IGNORECASE,
)

_RELATIONSHIP_KW = re.compile(
    r'\brelat\w*\b|\bconnect\w*\b|\bdepend\w*\b|\bbetween\b|\blinked\b'
    r'|\bсвязан\w*\b|\bзависи\w*\b|\bмежду\b',
    re.IGNORECASE,
)


def _rule_gate(query: str) -> str | None:
    """Fast deterministic classification via keyword/regex rules.

    Returns a profile name if exactly one profile matches.
    Returns None if 0 or 2+ profiles match (caller should use LLM fallback).
    """
    matched: set[str] = set()

    # execution: Jira key or status keywords
    if _JIRA_KEY_RE.search(query) or _EXECUTION_KW.search(query):
        matched.add("execution")

    # temporal: date expressions or time keywords
    try:
        date_range = extract_date_range(query)
    except Exception:
        date_range = None
    if date_range or _TEMPORAL_KW.search(query):
        matched.add("temporal")

    # user_file: upload/file keywords
    if _USER_FILE_KW.search(query):
        matched.add("user_file")

    # relationship: entity connection keywords
    if _RELATIONSHIP_KW.search(query):
        matched.add("relationship")

    # documentation has no rule gate (too broad, handled by LLM)

    if len(matched) == 1:
        return matched.pop()
    return None
```

Note: move `import re` to the top of the file (after `import structlog`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_query_classifier.py::TestRuleGate -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Run all classifier tests so far**

Run: `pytest tests/unit/test_query_classifier.py -v`
Expected: PASS (all 27 tests)

- [ ] **Step 6: Commit**

```bash
git add src/metatron/retrieval/query_classifier.py tests/unit/test_query_classifier.py
git commit -m "feat(classifier): add rule gate for keyword-based classification"
```

---

### Task 4: LLM fallback

**Files:**
- Modify: `src/metatron/retrieval/query_classifier.py`
- Test: `tests/unit/test_query_classifier.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_query_classifier.py`:

```python
from unittest.mock import patch


class TestLLMFallback:
    """LLM fallback for queries the rule gate can't classify."""

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_returns_llm_profile(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = '{"profile": "documentation", "confidence": 0.9}'
        result = _llm_classify("What is Metatron?")
        assert result["profile"] == "documentation"
        assert result["confidence"] == 0.9

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_low_confidence_returns_mixed(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = '{"profile": "documentation", "confidence": 0.3}'
        result = _llm_classify("vague query")
        assert result["profile"] == "mixed"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_invalid_json_returns_mixed(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = "not json at all"
        result = _llm_classify("some query")
        assert result["profile"] == "mixed"
        assert result["method"] == "default"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_unknown_profile_returns_mixed(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = '{"profile": "nonexistent", "confidence": 0.95}'
        result = _llm_classify("some query")
        assert result["profile"] == "mixed"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_timeout_returns_mixed(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.side_effect = TimeoutError("LLM timeout")
        result = _llm_classify("some query")
        assert result["profile"] == "mixed"
        assert result["method"] == "default"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_exception_returns_mixed(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.side_effect = RuntimeError("connection failed")
        result = _llm_classify("some query")
        assert result["profile"] == "mixed"
        assert result["method"] == "default"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_llm_called_with_correct_params(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = '{"profile": "execution", "confidence": 0.8}'
        _llm_classify("test query")

        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["timeout"] == 10
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "test query"

    @patch("metatron.retrieval.query_classifier.chat_completion")
    def test_llm_prompt_mentions_all_profiles(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import _llm_classify

        mock_llm.return_value = '{"profile": "mixed", "confidence": 0.5}'
        _llm_classify("test query")

        system_prompt = mock_llm.call_args.kwargs["messages"][0]["content"]
        for profile in ("execution", "documentation", "user_file", "relationship", "temporal", "mixed"):
            assert profile in system_prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_query_classifier.py::TestLLMFallback -v`
Expected: FAIL — `ImportError: cannot import name '_llm_classify'`

- [ ] **Step 3: Implement LLM fallback**

Add to `src/metatron/retrieval/query_classifier.py`, after `_rule_gate`:

```python
import json

from metatron.llm import chat_completion

_CLASSIFIER_SYSTEM_PROMPT = """\
You are a query intent classifier. Given a search query, classify it into one of 6 profiles.

Profiles:
- "execution": Task status, Jira tickets, current work, sprint, who is doing what. \
Examples: "What is the status of MTRNIX-104?", "What tasks are in progress?"
- "documentation": Architecture, concepts, explanations, how things work. \
Examples: "What is Metatron?", "How does RBAC work?"
- "user_file": Questions about uploaded files, reports, PDFs. \
Examples: "What does the 10K report say?", "Summarize the uploaded document"
- "relationship": Connections between entities, dependencies, links. \
Examples: "How does RBAC relate to user docs?", "What depends on the auth module?"
- "temporal": Date-bound, recent activity, sprints, time ranges. \
Examples: "What was done last week?", "Show documentation updated in 2026"
- "mixed": Unclear intent or spans multiple categories. Use when unsure.

Respond with JSON only: {"profile": "<name>", "confidence": <0.0-1.0>}"""

_VALID_PROFILES = frozenset(QUERY_PROFILE_WEIGHTS.keys())


def _llm_classify(query: str) -> QueryClassification:
    """Classify query via LLM. Returns mixed on any failure."""
    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=60,
            timeout=10,
        )
        parsed = json.loads(raw.strip())
        profile = parsed.get("profile", "mixed")
        confidence = float(parsed.get("confidence", 0.0))

        if profile not in _VALID_PROFILES or confidence < 0.5:
            return {"profile": "mixed", "confidence": confidence, "method": "default"}

        return {"profile": profile, "confidence": confidence, "method": "llm"}
    except Exception:
        logger.warning("query_classifier.llm_failed", query=query[:100])
        return {"profile": "mixed", "confidence": 0.0, "method": "default"}
```

Note: move `import json` to the top of the file. Add `from metatron.llm import chat_completion` to imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_query_classifier.py::TestLLMFallback -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/metatron/retrieval/query_classifier.py tests/unit/test_query_classifier.py
git commit -m "feat(classifier): add LLM fallback for ambiguous queries"
```

---

### Task 5: `classify_query()` orchestrator

**Files:**
- Modify: `src/metatron/retrieval/query_classifier.py`
- Test: `tests/unit/test_query_classifier.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_query_classifier.py`:

```python
class TestClassifyQuery:
    """classify_query() orchestrates rule gate → LLM fallback."""

    def test_rule_gate_match_skips_llm(self) -> None:
        from metatron.retrieval.query_classifier import classify_query

        with patch("metatron.retrieval.query_classifier._llm_classify") as mock_llm:
            result = classify_query("What is MTRNIX-104?")
            mock_llm.assert_not_called()
        assert result["profile"] == "execution"
        assert result["method"] == "rule"
        assert result["confidence"] == 1.0

    @patch("metatron.retrieval.query_classifier._llm_classify")
    def test_no_rule_match_calls_llm(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import classify_query

        mock_llm.return_value = {"profile": "documentation", "confidence": 0.85, "method": "llm"}
        result = classify_query("What is Metatron?")
        mock_llm.assert_called_once()
        assert result["profile"] == "documentation"

    @patch("metatron.retrieval.query_classifier._llm_classify")
    def test_ambiguous_query_calls_llm(self, mock_llm) -> None:
        from metatron.retrieval.query_classifier import classify_query

        mock_llm.return_value = {"profile": "temporal", "confidence": 0.7, "method": "llm"}
        # Matches both execution ("in progress") and temporal ("last week")
        result = classify_query("What was in progress last week?")
        mock_llm.assert_called_once()
        assert result["profile"] == "temporal"

    def test_uses_original_query_not_translated(self) -> None:
        """Classifier should run on original query (rq), not expanded."""
        from metatron.retrieval.query_classifier import classify_query

        # Russian query with Jira key — rule gate should catch it
        result = classify_query("Статус MTRNIX-104?")
        assert result["profile"] == "execution"
        assert result["method"] == "rule"

    def test_translated_query_checked_for_english_keywords(self) -> None:
        """For Russian queries, translated_query is checked for English keywords too."""
        from metatron.retrieval.query_classifier import classify_query

        with patch("metatron.retrieval.query_classifier._llm_classify") as mock_llm:
            mock_llm.return_value = {"profile": "user_file", "confidence": 0.8, "method": "llm"}
            # translated_query contains "uploaded file" → user_file via rule gate
            result = classify_query(
                "Что в документе?",
                translated_query="What is in the uploaded file?",
            )
            mock_llm.assert_not_called()
        assert result["profile"] == "user_file"

    def test_exception_in_classify_returns_mixed(self) -> None:
        from metatron.retrieval.query_classifier import classify_query

        with patch("metatron.retrieval.query_classifier._rule_gate", side_effect=RuntimeError("boom")):
            result = classify_query("any query")
        assert result["profile"] == "mixed"
        assert result["method"] == "default"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_query_classifier.py::TestClassifyQuery -v`
Expected: FAIL — `ImportError: cannot import name 'classify_query'`

- [ ] **Step 3: Implement `classify_query()`**

Add to `src/metatron/retrieval/query_classifier.py`, after `_llm_classify`:

```python
def classify_query(
    query: str,
    translated_query: str | None = None,
) -> QueryClassification:
    """Classify query intent into a profile for weight selection.

    Uses rule gate first (fast, deterministic). Falls back to LLM for
    ambiguous queries. Any exception returns 'mixed' (graceful degradation).

    Args:
        query: Original user query (rq).
        translated_query: English translation of query (for Russian queries).
            If None, only the original query is checked by the rule gate.
    """
    try:
        # Rule gate: check original query
        profile = _rule_gate(query)

        # For Russian queries, also check translated version for English keywords
        if profile is None and translated_query and translated_query != query:
            profile = _rule_gate(translated_query)

        if profile is not None:
            logger.info("query_classifier.rule", profile=profile, query=query[:100])
            return {"profile": profile, "confidence": 1.0, "method": "rule"}

        # LLM fallback
        result = _llm_classify(query)
        logger.info(
            "query_classifier.llm",
            profile=result["profile"],
            confidence=result["confidence"],
            query=query[:100],
        )
        return result
    except Exception:
        logger.warning("query_classifier.failed", query=query[:100])
        return {"profile": "mixed", "confidence": 0.0, "method": "default"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_query_classifier.py::TestClassifyQuery -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run all classifier tests**

Run: `pytest tests/unit/test_query_classifier.py -v`
Expected: PASS (all 41 tests)

- [ ] **Step 6: Commit**

```bash
git add src/metatron/retrieval/query_classifier.py tests/unit/test_query_classifier.py
git commit -m "feat(classifier): add classify_query() orchestrator with rule gate + LLM fallback"
```

---

### Task 6: Pipeline integration in `search.py`

**Files:**
- Modify: `src/metatron/retrieval/search.py:417` (after query expansion, before recall), `search.py:469-479` (scoring loop), `search.py:494-498` (blend), `search.py:591-607` (trace)
- Modify: `tests/unit/test_search_trace_extended.py` (add classify_query patch + verify new trace fields)
- Test: `tests/unit/test_query_classifier.py`

- [ ] **Step 1: Write the failing integration test**

Append to `tests/unit/test_query_classifier.py`:

```python
class TestSearchIntegration:
    """Verify classify_query is called in the search pipeline."""

    def test_classifier_called_in_search(self) -> None:
        """When enabled, classify_query is called with original query."""
        from tests.unit.test_search_trace_extended import _patch_search_internals

        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metatron.retrieval.search import hybrid_search_and_answer

            with patch("metatron.retrieval.search.classify_query") as mock_cls:
                mock_cls.return_value = {"profile": "mixed", "confidence": 1.0, "method": "rule"}
                hybrid_search_and_answer(
                    query="What is Metatron?",
                    return_trace=True,
                    workspace_id="ws_test",
                )
                mock_cls.assert_called_once()
                # First arg is the original query (rq)
                assert mock_cls.call_args.args[0] == "What is Metatron?"
        finally:
            for p in patches.values():
                p.stop()

    def test_classifier_disabled_uses_mixed(self) -> None:
        from tests.unit.test_search_trace_extended import _patch_search_internals

        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metatron.retrieval.search import hybrid_search_and_answer

            with patch("metatron.retrieval.search.classify_query") as mock_cls, \
                 patch("metatron.core.config.Settings.query_classifier_enabled", False):
                hybrid_search_and_answer(
                    query="What is Metatron?",
                    return_trace=True,
                    workspace_id="ws_test",
                )
                mock_cls.assert_not_called()
        finally:
            for p in patches.values():
                p.stop()

    def test_trace_includes_classifier_fields(self) -> None:
        from tests.unit.test_search_trace_extended import _patch_search_internals

        patches = _patch_search_internals()
        for p in patches.values():
            p.start()

        try:
            from metatron.retrieval.search import hybrid_search_and_answer

            with patch("metatron.retrieval.search.classify_query") as mock_cls:
                mock_cls.return_value = {"profile": "documentation", "confidence": 0.9, "method": "llm"}
                result = hybrid_search_and_answer(
                    query="What is Metatron?",
                    return_trace=True,
                    workspace_id="ws_test",
                )
                stages = result["pipeline_stages"]
                assert stages["query_profile"] == "documentation"
                assert stages["query_profile_method"] == "llm"
                assert stages["query_profile_confidence"] == 0.9
        finally:
            for p in patches.values():
                p.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_query_classifier.py::TestSearchIntegration -v`
Expected: FAIL — `ImportError: cannot import name 'classify_query' from 'metatron.retrieval.search'`

- [ ] **Step 3: Add classifier call to search.py**

In `src/metatron/retrieval/search.py`, add import at line ~29 (with other retrieval imports):

```python
from metatron.retrieval.query_classifier import classify_query, get_profile_weights
```

After line 417 (`sq = translate_query_to_english(eq) if _has_cyrillic(eq) else eq`), add:

```python
    # -- Classify query intent --
    if _s.query_classifier_enabled:
        _translated_for_classifier = (
            translate_query_to_english(rq) if _has_cyrillic(rq) else rq
        )
        classification = classify_query(rq, translated_query=_translated_for_classifier)
    else:
        classification = {"profile": "mixed", "confidence": 1.0, "method": "disabled"}

    _profile_weights = get_profile_weights(classification["profile"])
```

- [ ] **Step 4: Replace Settings weights with profile weights in scoring loop**

In the scoring loop (lines ~469-479), replace:

```python
        mr["signal_score"] = compute_signal_score(
            channel_scores=mr["channel_scores"],
            recency=rec,
            balance=bal,
            dense_weight=_s.dense_weight,
            sparse_weight=_s.sparse_weight,
            graph_weight=_s.graph_weight,
            metadata_weight=_s.metadata_weight,
            recency_weight=_s.recency_weight,
            balance_weight=_s.balance_weight,
        )
```

with (placed before the `for mr in merged:` loop, since it's constant per query):

```python
    _scoring_weights = {k: v for k, v in _profile_weights.items() if k != "blend_weight"}
```

And inside the loop, replace the `compute_signal_score` call with:

```python
        mr["signal_score"] = compute_signal_score(
            channel_scores=mr["channel_scores"],
            recency=rec,
            balance=bal,
            **_scoring_weights,
        )
```

- [ ] **Step 5: Replace blend_weight in compute_final_score**

In the reranker block (line ~497), replace:

```python
                blend_weight=_s.blend_weight,
```

with:

```python
                blend_weight=_profile_weights["blend_weight"],
```

- [ ] **Step 6: Add trace fields to pipeline_stages**

In the `pipeline_stages` dict (line ~591-607), add these three fields after existing fields:

```python
                "query_profile": classification["profile"],
                "query_profile_method": classification["method"],
                "query_profile_confidence": classification["confidence"],
```

- [ ] **Step 7: Run integration tests to verify they pass**

Run: `pytest tests/unit/test_query_classifier.py::TestSearchIntegration -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Update `_patch_search_internals()` in trace test**

In `tests/unit/test_search_trace_extended.py`, add a `classify_query` patch to `_patch_search_internals()`:

```python
        "classify_query": patch(
            f"{_SEARCH_MODULE}.classify_query",
            return_value={"profile": "mixed", "confidence": 1.0, "method": "rule"},
        ),
```

- [ ] **Step 9: Update expected trace subkeys in trace test**

In `tests/unit/test_search_trace_extended.py`, `test_pipeline_stages_has_all_subkeys`, add to `expected_subkeys`:

```python
                "query_profile",
                "query_profile_method",
                "query_profile_confidence",
```

- [ ] **Step 10: Run all existing tests to verify no regressions**

Run: `pytest tests/unit/test_search_trace_extended.py tests/unit/test_diversify_results.py tests/unit/test_name_aliases.py -v`
Expected: PASS (all existing tests still pass)

- [ ] **Step 11: Run full classifier test suite**

Run: `pytest tests/unit/test_query_classifier.py -v`
Expected: PASS (all ~44 tests)

- [ ] **Step 12: Run full unit test suite**

Run: `make test`
Expected: All unit tests pass (existing 915+ plus new ~44)

- [ ] **Step 13: Commit**

```bash
git add src/metatron/retrieval/search.py src/metatron/retrieval/query_classifier.py \
  tests/unit/test_query_classifier.py tests/unit/test_search_trace_extended.py
git commit -m "feat(classifier): integrate query classifier into search pipeline"
```

---

### Task 7: Final verification and eval

- [ ] **Step 1: Run full test suite**

Run: `make test`
Expected: All tests pass, zero regressions.

- [ ] **Step 2: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: No new errors.

- [ ] **Step 3: Manual smoke test — verify disabled mode**

Run:
```bash
QUERY_CLASSIFIER_ENABLED=false python -c "
from metatron.core.config import Settings
s = Settings()
assert s.query_classifier_enabled is False
print('OK: classifier disabled')
"
```
Expected: prints "OK: classifier disabled"

- [ ] **Step 4: Commit any final fixes**

If lint/typecheck required fixes:
```bash
git add -u
git commit -m "fix(classifier): lint and type fixes"
```
