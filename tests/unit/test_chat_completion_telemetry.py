"""Unit tests for LLM telemetry integration in chat_completion (PROJ-336).

Coverage:
- Provider success → emit_log called with correct fields (call_site, model,
  provider, tokens, latency >= 0, success=True, fallback_used=False).
- Provider returns empty content → row has success=False, error_class="EmptyResponse";
  caller still receives "" (no behaviour change).
- Primary raises LLMConnectionError, fallback succeeds → one row with
  success=True, fallback_used=True.
- Primary raises LLMConnectionError, no fallback → success=False, error re-raised.
- chat_completion_with_retry with N transient failures then success → N+1 rows.
- Empty usage dict → prompt_tokens=0, completion_tokens=0, zero_tokens=True in metadata.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from metronix.llm.base import LLMConnectionError, LLMResponse

# emit_log is imported into metronix.llm at module load time, so the patch
# target is the LOCAL binding inside metronix.llm — not metronix.llm.telemetry.
_EMIT_LOG_PATH = "metronix.llm.emit_log"
# Real storage insert path — patching here works regardless of import order.
_INSERT_PATH = "metronix.storage.llm_generation_log.insert_log_row_sync"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(
    name: str = "mock_provider",
    model: str = "mock-model",
    content: str = "hello",
    usage: dict | None = None,
    side_effect: Exception | None = None,
) -> MagicMock:
    provider = MagicMock()
    provider.name = name
    provider.model = model
    provider.is_available.return_value = True
    if side_effect is not None:
        provider.chat_completion.side_effect = side_effect
    else:
        default_usage = {
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "total_tokens": 8,
        }
        provider.chat_completion.return_value = LLMResponse(
            content=content,
            model=model,
            provider=name,
            usage=usage if usage is not None else default_usage,
        )
    return provider


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_emit_log_called_on_success() -> None:
    provider = _make_provider(name="ollama", model="llama3")

    captured: list[dict] = []

    def fake_emit(**kwargs: object) -> None:
        captured.append(dict(kwargs))

    with (
        patch("metronix.llm.get_llm", return_value=provider),
        patch("metronix.llm._get_cached_fallback", return_value=None),
        patch(_EMIT_LOG_PATH, side_effect=fake_emit),
    ):
        from metronix.llm import chat_completion

        result = chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            call_site="rag_answer",
        )

    assert result == "hello"
    assert len(captured) == 1
    row = captured[0]
    assert row["call_site"] == "rag_answer"
    assert row["provider"] == "ollama"
    assert row["model"] == "llama3"
    assert row["success"] is True
    assert row["fallback_used"] is False
    assert row["fallback_provider"] is None
    assert row["error_class"] is None
    assert row["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# Empty content → EmptyResponse
# ---------------------------------------------------------------------------


def test_empty_response_emits_failure_row_but_caller_gets_empty_string() -> None:
    provider = _make_provider(name="ollama", model="llama3", content="")

    captured: list[dict] = []

    def fake_emit(**kwargs: object) -> None:
        captured.append(dict(kwargs))

    with (
        patch("metronix.llm.get_llm", return_value=provider),
        patch("metronix.llm._get_cached_fallback", return_value=None),
        patch(_EMIT_LOG_PATH, side_effect=fake_emit),
    ):
        from metronix.llm import chat_completion

        result = chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            call_site="rag_answer",
        )

    # Caller receives empty string — behaviour is unchanged.
    assert result == ""
    assert len(captured) == 1
    row = captured[0]
    assert row["success"] is False
    assert row["error_class"] == "EmptyResponse"


# ---------------------------------------------------------------------------
# Fallback success
# ---------------------------------------------------------------------------


def test_fallback_success_emits_one_row_with_fallback_used() -> None:
    primary = _make_provider(
        name="deepseek",
        model="deepseek-chat",
        side_effect=LLMConnectionError("timeout"),
    )
    fallback = _make_provider(name="ollama", model="llama3", content="fallback result")

    captured: list[dict] = []

    def fake_emit(**kwargs: object) -> None:
        captured.append(dict(kwargs))

    with (
        patch("metronix.llm.get_llm", return_value=primary),
        patch("metronix.llm._get_cached_fallback", return_value=fallback),
        patch(_EMIT_LOG_PATH, side_effect=fake_emit),
    ):
        from metronix.llm import chat_completion

        result = chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            call_site="rag_answer",
            use_fallback=True,
        )

    assert result == "fallback result"
    assert len(captured) == 1
    row = captured[0]
    assert row["success"] is True
    assert row["fallback_used"] is True
    assert row["fallback_provider"] == "ollama"


# ---------------------------------------------------------------------------
# No fallback → failure row + exception re-raised
# ---------------------------------------------------------------------------


def test_no_fallback_emits_failure_row_and_raises() -> None:
    primary = _make_provider(
        name="ollama",
        model="llama3",
        side_effect=LLMConnectionError("network error"),
    )

    captured: list[dict] = []

    def fake_emit(**kwargs: object) -> None:
        captured.append(dict(kwargs))

    with (
        patch("metronix.llm.get_llm", return_value=primary),
        patch("metronix.llm._get_cached_fallback", return_value=None),
        patch(_EMIT_LOG_PATH, side_effect=fake_emit),
    ):
        from metronix.llm import chat_completion

        with pytest.raises(LLMConnectionError):
            chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                call_site="rag_answer",
                use_fallback=True,  # fallback=None, so effectively no fallback
            )

    assert len(captured) == 1
    row = captured[0]
    assert row["success"] is False
    assert row["error_class"] == "LLMConnectionError"


# ---------------------------------------------------------------------------
# chat_completion_with_retry — N failures then success → N+1 rows
# ---------------------------------------------------------------------------


def test_retry_produces_failure_then_success_rows() -> None:
    ok_response = LLMResponse(
        content="ok",
        model="llama3",
        provider="ollama",
        usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    )
    err = LLMConnectionError("transient")

    # 2 failures then success
    provider = MagicMock()
    provider.name = "ollama"
    provider.model = "llama3"
    provider.is_available.return_value = True
    provider.chat_completion.side_effect = [err, err, ok_response]

    captured: list[dict] = []

    def fake_emit(**kwargs: object) -> None:
        captured.append(dict(kwargs))

    with (
        patch("metronix.llm.get_llm", return_value=provider),
        patch("metronix.llm._get_cached_fallback", return_value=None),
        patch(_EMIT_LOG_PATH, side_effect=fake_emit),
        patch("metronix.llm.time.sleep"),  # don't actually sleep
    ):
        from metronix.llm import chat_completion_with_retry

        result = chat_completion_with_retry(
            messages=[{"role": "user", "content": "hi"}],
            call_site="rag_answer",
            max_retries=3,
            use_fallback=False,
        )

    assert result == "ok"
    # 2 failures + 1 success = 3 emit_log calls
    assert len(captured) == 3
    assert captured[0]["success"] is False
    assert captured[1]["success"] is False
    assert captured[2]["success"] is True


# ---------------------------------------------------------------------------
# Empty usage dict → zero_tokens=True in metadata
# ---------------------------------------------------------------------------


def test_empty_usage_dict_yields_zero_tokens_metadata() -> None:
    provider = _make_provider(name="custom", model="local", usage={})

    # We patch insert_log_row_sync to capture the metadata built inside emit_log.
    rows_captured: list = []

    def fake_insert(row: object) -> None:
        rows_captured.append(row)

    import metronix.llm.telemetry as tel_mod

    with (
        patch("metronix.llm.get_llm", return_value=provider),
        patch("metronix.llm._get_cached_fallback", return_value=None),
        patch.object(
            tel_mod,
            "get_settings",
            return_value=MagicMock(
                llm_telemetry_enabled=True,
                llm_telemetry_opt_out_cache_ttl_seconds=60,
            ),
        ),
        patch(_INSERT_PATH, side_effect=fake_insert),
    ):
        from metronix.llm import chat_completion

        chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            call_site="rag_answer",
            use_fallback=False,
        )

    assert len(rows_captured) == 1
    metadata = rows_captured[0].metadata
    assert metadata["zero_tokens"] is True
