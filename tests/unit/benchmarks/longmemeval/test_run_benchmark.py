from __future__ import annotations

import json
import sys
from pathlib import Path

BENCH_SCRIPTS = Path(__file__).resolve().parents[4] / "benchmarks" / "longmemeval" / "scripts"
sys.path.insert(0, str(BENCH_SCRIPTS))

from metronix_client import _parse_tool_payload  # noqa: E402
from run_benchmark import (  # noqa: E402
    append_result,
    format_session_text,
    load_completed_ids,
)


def test_format_session_text_includes_date() -> None:
    session = [{"role": "user", "content": "Hello"}]
    text = format_session_text(session, date="2024-01-01")
    assert "[Conversation date: 2024-01-01]" in text
    assert "User: Hello" in text


def test_jsonl_resume_skips_completed_ids(tmp_path: Path) -> None:
    output = tmp_path / "results.jsonl"
    append_result(output, "q1", "answer one")
    append_result(output, "q2", "answer two")

    done = load_completed_ids(output)
    assert done == {"q1", "q2"}

    dataset = [
        {"question_id": "q1", "question": "Q1"},
        {"question_id": "q2", "question": "Q2"},
        {"question_id": "q3", "question": "Q3"},
    ]
    remaining = [entry for entry in dataset if entry["question_id"] not in done]
    assert [entry["question_id"] for entry in remaining] == ["q3"]


def test_append_result_creates_parent_dirs(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "out.jsonl"
    append_result(output, "q1", "hypothesis")
    lines = output.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0]) == {"question_id": "q1", "hypothesis": "hypothesis"}


def test_parse_tool_payload_from_json_text() -> None:
    class Block:
        text = '{"results": [{"record": {"content": "hello"}}], "count": 1}'

    class Result:
        content = [Block()]

    payload = _parse_tool_payload(Result())
    assert payload["count"] == 1
    assert payload["results"][0]["record"]["content"] == "hello"


def test_parse_tool_payload_from_dict() -> None:
    payload = _parse_tool_payload({"id": "abc", "deduped": False})
    assert payload["id"] == "abc"
