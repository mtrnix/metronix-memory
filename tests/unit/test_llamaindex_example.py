"""Regression checks for examples/llamaindex_metronix_example.py.

The example doubles as the LlamaIndex guide's "Verify" step, so it must exit
non-zero when a pass fails — a shell/CI caller otherwise reads a failed memory
round-trip or an empty retrieval as success (toomij99, PR #439).

llama-index is intentionally *not* a project dependency (the guide installs the
client packages in a separate venv), so the module's top-level imports are
stubbed here to load it without that tree.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "examples" / "llamaindex_metronix_example.py"


def _llama_index_stubs() -> dict[str, types.ModuleType]:
    """Minimal stand-ins for the llama_index names the example imports."""

    def _mod(name: str, **attrs: object) -> types.ModuleType:
        m = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(m, key, value)
        return m

    class _BaseRetriever:  # subclassed by MetronixRetriever at import time
        def __init__(self, *args: object, **kwargs: object) -> None: ...

    return {
        "llama_index": types.ModuleType("llama_index"),
        "llama_index.core": _mod(
            "llama_index.core",
            QueryBundle=type("QueryBundle", (), {}),
            get_response_synthesizer=lambda **_: None,
        ),
        "llama_index.core.async_utils": _mod(
            "llama_index.core.async_utils", asyncio_run=lambda coro: None
        ),
        "llama_index.core.query_engine": _mod(
            "llama_index.core.query_engine",
            RetrieverQueryEngine=type("RetrieverQueryEngine", (), {}),
        ),
        "llama_index.core.retrievers": _mod(
            "llama_index.core.retrievers", BaseRetriever=_BaseRetriever
        ),
        "llama_index.core.schema": _mod(
            "llama_index.core.schema",
            NodeWithScore=type("NodeWithScore", (), {}),
            TextNode=type("TextNode", (), {}),
        ),
        "llama_index.llms": types.ModuleType("llama_index.llms"),
        "llama_index.llms.openai_like": _mod(
            "llama_index.llms.openai_like", OpenAILike=type("OpenAILike", (), {})
        ),
        "llama_index.tools": types.ModuleType("llama_index.tools"),
        "llama_index.tools.mcp": _mod(
            "llama_index.tools.mcp", BasicMCPClient=type("BasicMCPClient", (), {})
        ),
    }


@pytest.fixture
def example(monkeypatch: pytest.MonkeyPatch) -> object:
    for name, module in _llama_index_stubs().items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("_llamaindex_example_under_test", _EXAMPLE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestVerificationFailures:
    def test_both_passes_ok_is_empty(self, example: object) -> None:
        assert example._verification_failures(3, True) == []

    def test_zero_nodes_is_a_failure(self, example: object) -> None:
        failures = example._verification_failures(0, True)
        assert len(failures) == 1
        assert "no nodes" in failures[0]

    def test_memory_miss_is_a_failure(self, example: object) -> None:
        failures = example._verification_failures(5, False)
        assert len(failures) == 1
        assert "memory round-trip" in failures[0]

    def test_both_failing_reports_both(self, example: object) -> None:
        assert len(example._verification_failures(0, False)) == 2


class TestMainExitStatus:
    def _wire(
        self,
        example: object,
        monkeypatch: pytest.MonkeyPatch,
        *,
        nodes: int,
        retrieved: bool,
    ) -> None:
        monkeypatch.setattr(example, "METRONIX_MCP_TOKEN", "mtk_test")
        monkeypatch.setattr(example, "_build_client", lambda: object())
        monkeypatch.setattr(example.sys, "argv", ["example", "a question"])

        async def _retrieval_pass(_client: object, _question: str) -> int:
            return nodes

        async def _memory_pass(_client: object, _fact: str) -> bool:
            return retrieved

        monkeypatch.setattr(example, "retrieval_pass", _retrieval_pass)
        monkeypatch.setattr(example, "memory_pass", _memory_pass)

    def test_exits_nonzero_when_memory_round_trip_fails(
        self, example: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wire(example, monkeypatch, nodes=3, retrieved=False)
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(example.main())
        assert exc_info.value.code == 1

    def test_exits_nonzero_when_retrieval_returns_no_nodes(
        self, example: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wire(example, monkeypatch, nodes=0, retrieved=True)
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(example.main())
        assert exc_info.value.code == 1

    def test_exits_zero_when_both_passes_succeed(
        self, example: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wire(example, monkeypatch, nodes=3, retrieved=True)
        asyncio.run(example.main())  # no SystemExit


class _FakeNode:
    def __init__(self, doc_label: str, url: str = "", score: float = 0.5) -> None:
        self.node = types.SimpleNamespace(metadata={"doc_label": doc_label, "url": url})
        self.score = score


class _FakeAnswer:
    def __init__(self, source_nodes: list[_FakeNode]) -> None:
        self.source_nodes = source_nodes

    def __str__(self) -> str:
        return "synthesized answer"


class _EngineSpy:
    """Records how retrieval_pass drives retrieval."""

    def __init__(self, source_nodes: list[_FakeNode]) -> None:
        self._source_nodes = source_nodes
        self.direct_retrieves = 0
        self.aquery_questions: list[str] = []
        self.retriever: object = None
        self.engine_retriever: object = None

    def install(self, example: object, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = self

        class _FakeRetriever:
            def __init__(self, _client: object, *, top_k: int = 5) -> None:
                self.top_k = top_k

            async def aretrieve(self, _q: str) -> list[_FakeNode]:
                spy.direct_retrieves += 1
                return []

            async def _aretrieve(self, _qb: object) -> list[_FakeNode]:
                spy.direct_retrieves += 1
                return []

        class _FakeEngine:
            def __init__(self, *, retriever: object, response_synthesizer: object) -> None:
                spy.engine_retriever = retriever

            async def aquery(self, question: str) -> _FakeAnswer:
                spy.aquery_questions.append(question)
                return _FakeAnswer(spy._source_nodes)

        def _make_retriever(client: object, *, top_k: int = 5) -> _FakeRetriever:
            spy.retriever = _FakeRetriever(client, top_k=top_k)
            return spy.retriever

        monkeypatch.setattr(example, "MetronixRetriever", _make_retriever)
        monkeypatch.setattr(example, "OpenAILike", lambda **_: object())
        monkeypatch.setattr(example, "get_response_synthesizer", lambda **_: object())
        monkeypatch.setattr(example, "RetrieverQueryEngine", _FakeEngine)


class TestRetrievalPassSingleRetrieval:
    """retrieval_pass must retrieve exactly once — through the query engine.

    An eager retriever.aretrieve() before engine.aquery() issued a second
    metronix_search_fast request whose ranking could diverge from the passages
    the answer was actually grounded on (toomij99, PR #439).
    """

    def test_retrieves_once_through_the_engine(
        self, example: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        nodes = [_FakeNode("KB-A", score=0.41), _FakeNode("KB-B", url="https://x/y", score=0.33)]
        spy = _EngineSpy(nodes)
        spy.install(example, monkeypatch)

        count = asyncio.run(example.retrieval_pass(object(), "how does retrieval work?"))

        assert count == 2
        assert spy.aquery_questions == ["how does retrieval work?"]
        assert spy.direct_retrieves == 0  # no second metronix_search_fast request
        assert spy.engine_retriever is spy.retriever
        out = capsys.readouterr().out
        assert "[retrieve] 2 node(s)" in out
        assert "KB-A" in out and "KB-B" in out

    def test_empty_retrieval_reports_zero_without_a_direct_call(
        self, example: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        spy = _EngineSpy([])
        spy.install(example, monkeypatch)

        count = asyncio.run(example.retrieval_pass(object(), "q"))

        assert count == 0
        assert spy.direct_retrieves == 0
        assert spy.aquery_questions == ["q"]
        assert "nothing indexed yet" in capsys.readouterr().out
