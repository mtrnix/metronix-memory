"""LLM generation requests are sent once: a read timeout is raised, not re-sent.

The shared session retries reads (3 retries, POST included), which is right for
embeddings but turned one slow extraction call into four generations of a full
timeout each, times the extraction loop's own three attempts.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from metronix.core import http


class _SlowHandler(BaseHTTPRequestHandler):
    posts: list[float] = []

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        type(self).posts.append(time.monotonic())
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        time.sleep(1.0)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"message": {"content": "{}"}}')
        except OSError:
            pass  # the client gave up

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def slow_server():
    _SlowHandler.posts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    http.close_http_session()


def test_generation_session_sends_a_timed_out_post_once(slow_server) -> None:
    import requests

    with pytest.raises(requests.exceptions.ReadTimeout):
        http.get_generation_session().post(f"{slow_server}/api/chat", json={}, timeout=0.2)
    time.sleep(0.3)
    assert len(_SlowHandler.posts) == 1


def test_ollama_timeout_is_typed_and_sent_once(slow_server) -> None:
    from metronix.llm import LLMTimeoutError, Message
    from metronix.llm.providers.ollama import OllamaProvider

    provider = OllamaProvider(model="qwen2.5:3b", host=slow_server)
    with pytest.raises(LLMTimeoutError):
        provider.chat_completion([Message(role="user", content="hi")], timeout=0.2)
    time.sleep(0.3)
    assert len(_SlowHandler.posts) == 1


def test_generation_and_shared_sessions_are_separate() -> None:
    assert http.get_generation_session() is not http.get_http_session()
    assert http.get_generation_session() is http.get_generation_session()
    http.close_http_session()
