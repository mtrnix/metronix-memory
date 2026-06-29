"""Query rewrite stage (PROJ-372 P2)."""

from unittest.mock import MagicMock

from metronix.core.config import Settings
from metronix.memory.query_rewrite import QueryRewriter, _needs_rewrite, last_user_message


def test_last_user_message() -> None:
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "second"},
    ]
    assert last_user_message(msgs) == "second"


def test_last_user_message_empty() -> None:
    assert last_user_message([{"role": "assistant", "content": "x"}]) == ""


def test_needs_rewrite_short() -> None:
    assert _needs_rewrite("who?") is True


def test_needs_rewrite_pronoun() -> None:
    assert _needs_rewrite("what about it then please") is True


def test_needs_rewrite_long_specific() -> None:
    assert _needs_rewrite("explain the billing reconciliation workflow in detail") is False


async def test_rewrite_disabled_returns_last_user_msg() -> None:
    s = Settings()  # proxy_query_rewrite_enabled defaults False
    rw = QueryRewriter(settings=s, provider_factory=lambda: MagicMock())
    msgs = [{"role": "user", "content": "tell me about it"}]
    query, used_slm, fallback = await rw.rewrite(msgs, timeout_s=0.4)
    assert query == "tell me about it"
    assert used_slm is False
    assert fallback is False


async def test_rewrite_enabled_uses_slm() -> None:
    s = Settings(METRONIX_PROXY_QUERY_REWRITE_ENABLED=True)

    class _Resp:
        content = "billing reconciliation status for ACME"

    provider = MagicMock()
    provider.chat_completion.return_value = _Resp()
    rw = QueryRewriter(settings=s, provider_factory=lambda: provider)
    msgs = [
        {"role": "user", "content": "what about it?"},
    ]
    query, used_slm, fallback = await rw.rewrite(msgs, timeout_s=0.4)
    assert query == "billing reconciliation status for ACME"
    assert used_slm is True
    assert fallback is False


async def test_rewrite_slm_error_falls_back() -> None:
    s = Settings(METRONIX_PROXY_QUERY_REWRITE_ENABLED=True)
    provider = MagicMock()
    provider.chat_completion.side_effect = RuntimeError("boom")
    rw = QueryRewriter(settings=s, provider_factory=lambda: provider)
    msgs = [{"role": "user", "content": "what about it?"}]
    query, used_slm, fallback = await rw.rewrite(msgs, timeout_s=0.4)
    assert query == "what about it?"
    assert fallback is True
