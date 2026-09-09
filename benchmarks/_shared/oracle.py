"""Oracle (evidence) session tags for a benchmark question.

The runners ingest one memory record per haystack session, tagged
``session_<idx>`` where ``idx`` is the 0-based position of that session in the
list handed to the MCP client. ``metronix_memory_search`` hits carry those tags,
so recall@k reduces to "is the oracle session's record in the top-k hits".

Abstention questions (LongMemEval ``*_abs`` ids, LoCoMo category 5) have no
correct retrieval target — callers exclude them from the recall aggregate.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Sequence

_LOCOMO_DIA_RE = re.compile(r"^D(\d+):\d+$")


def session_tag(index: int) -> str:
    return f"session_{index}"


def _is_session_tag(value: object) -> bool:
    return isinstance(value, str) and value.startswith("session_") and value[8:].isdigit()


def retrieved_session_tags(search_results: Sequence[dict]) -> list[str]:
    """Ordered ``session_<idx>`` tags, one per search hit.

    A hit is represented by its first ``session_*`` tag. Hits with none (should
    not happen for benchmark-ingested records) are dropped.
    """
    tags: list[str] = []
    for hit in search_results:
        record = hit.get("record") if isinstance(hit, dict) else None
        for tag in (record or {}).get("tags", []) or []:
            if _is_session_tag(tag):
                tags.append(tag)
                break
    return tags


# ---------------------------------------------------------------------------
# LongMemEval
# ---------------------------------------------------------------------------


def longmemeval_is_abstention(entry: dict) -> bool:
    return "_abs" in str(entry.get("question_id", ""))


def longmemeval_oracle_tags(entry: dict) -> set[str]:
    """Map ``answer_session_ids`` to ``session_<idx>`` via ``haystack_session_ids``."""
    position = {sid: i for i, sid in enumerate(entry.get("haystack_session_ids") or [])}
    return {
        session_tag(position[sid])
        for sid in entry.get("answer_session_ids") or []
        if sid in position
    }


# ---------------------------------------------------------------------------
# LoCoMo
# ---------------------------------------------------------------------------


def locomo_is_abstention(entry: dict) -> bool:
    try:
        return int(entry.get("category", 0)) == 5
    except (TypeError, ValueError):
        return False


def _parse_evidence(evidence: object) -> list[str]:
    """LoCoMo ``evidence`` is a Python-repr string like ``"['D1:3', 'D2:8']"``."""
    if isinstance(evidence, (list, tuple)):
        items: Sequence[object] = evidence
    elif isinstance(evidence, str):
        stripped = evidence.strip()
        if not stripped:
            return []
        if stripped[0] in "[(":
            try:
                parsed = ast.literal_eval(stripped)
            except (ValueError, SyntaxError):
                return []
            items = parsed if isinstance(parsed, (list, tuple)) else [parsed]
        else:
            items = [stripped]
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]


def locomo_oracle_tags(entry: dict) -> set[str]:
    """Map ``evidence`` dialogue refs (``D<n>:<turn>``) to ``session_<idx>``.

    ``entry["session_numbers"]`` is the sorted list of session numbers in the
    order the runner ingests them (see ``dataset.iter_questions``).
    """
    session_numbers = entry.get("session_numbers") or []
    order = {number: index for index, number in enumerate(session_numbers)}
    tags: set[str] = set()
    for ref in _parse_evidence(entry.get("evidence")):
        match = _LOCOMO_DIA_RE.match(ref)
        if match is not None and int(match.group(1)) in order:
            tags.add(session_tag(order[int(match.group(1))]))
    return tags
