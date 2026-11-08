"""The graph-extraction model is not pre-pulled; OllamaProvider pulls it on first use."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from metronix.llm.base import LLMError, Message
from metronix.llm.providers.ollama import OllamaProvider

MODEL = "qwen2.5:3b"
SESSION = "metronix.llm.providers.ollama.get_generation_session"


def _response(status: int, body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.text = str(body)
    if status >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status} error", response=resp
        )
    return resp


def _not_found() -> MagicMock:
    return _response(404, {"error": f'model "{MODEL}" not found, try pulling it first'})


def _chat_ok() -> MagicMock:
    return _response(200, {"message": {"content": "{}"}, "eval_count": 1})


def _provider() -> OllamaProvider:
    return OllamaProvider(model=MODEL, host="http://ollama:11434")


def _messages() -> list[Message]:
    return [Message(role="user", content="extract")]


def test_missing_model_is_pulled_then_chat_retried() -> None:
    session = MagicMock()
    session.post.side_effect = [_not_found(), _response(200, {"status": "success"}), _chat_ok()]
    with patch(SESSION, return_value=session):
        result = _provider().chat_completion(_messages())

    assert result.content == "{}"
    urls = [c.args[0] for c in session.post.call_args_list]
    assert urls == [
        "http://ollama:11434/api/chat",
        "http://ollama:11434/api/pull",
        "http://ollama:11434/api/chat",
    ]
    assert session.post.call_args_list[1].kwargs["json"] == {"model": MODEL, "stream": False}


def test_failed_pull_raises_llm_error() -> None:
    session = MagicMock()
    session.post.side_effect = [_not_found(), _response(500, {"error": "no space left"})]
    with patch(SESSION, return_value=session), pytest.raises(LLMError, match="pull"):
        _provider().chat_completion(_messages())


def test_other_http_errors_do_not_trigger_a_pull() -> None:
    session = MagicMock()
    session.post.side_effect = [_response(500, {"error": "boom"})]
    with patch(SESSION, return_value=session), pytest.raises(LLMError):
        _provider().chat_completion(_messages())
    assert session.post.call_count == 1
