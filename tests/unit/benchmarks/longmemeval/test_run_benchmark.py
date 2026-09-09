from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import pytest

BENCH_SCRIPTS = Path(__file__).resolve().parents[4] / "benchmarks" / "longmemeval" / "scripts"
sys.path.insert(0, str(BENCH_SCRIPTS))

import metronix_client  # noqa: E402
from metronix_client import MetronixMCPClient, _parse_tool_payload  # noqa: E402
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


class _FakeSession:
    def __init__(self) -> None:
        self.stored: list[dict] = []

    async def initialize(self) -> None:
        return None

    async def call_tool(self, name: str, args: dict):
        if name == "metronix_memory_store":
            self.stored.append(args)
            return {"id": f"rec-{len(self.stored)}"}
        return {"results": [{"record": {"tags": args["query"] and ["session_0"]}}]}


def test_ingest_and_search_returns_results_and_phase_timings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()

    @contextlib.asynccontextmanager
    async def fake_client_session(_read, _write):
        yield session

    @contextlib.asynccontextmanager
    async def fake_streamable(_url, http_client=None):
        yield (None, None, None)

    monkeypatch.setitem(sys.modules, "mcp", type("m", (), {"ClientSession": fake_client_session}))
    monkeypatch.setitem(
        sys.modules,
        "mcp.client.streamable_http",
        type("s", (), {"streamable_http_client": fake_streamable}),
    )
    monkeypatch.setattr(metronix_client.httpx, "AsyncClient", lambda **_kw: _NoopAsyncCM())

    client = MetronixMCPClient(mcp_url="http://x/mcp", api_key="k", workspace_id="W", agent_id="a")
    out = client.ingest_and_search(
        sessions=[[{"role": "user", "content": "hi"}], [{"role": "user", "content": "yo"}]],
        dates=["d1", "d2"],
        format_session_text=lambda turns, date="": "text",
        query="q",
        top_k=10,
    )

    assert list(out) == ["results", "ingest_ms", "search_ms"]
    assert isinstance(out["ingest_ms"], float) and out["ingest_ms"] >= 0.0
    assert isinstance(out["search_ms"], float) and out["search_ms"] >= 0.0
    assert out["results"] == [{"record": {"tags": ["session_0"]}}]
    assert len(session.stored) == 2  # one store per haystack session


class _NoopAsyncCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False
