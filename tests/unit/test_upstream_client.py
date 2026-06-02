"""UpstreamLLMClient streaming + error forwarding (MTRNIX-372 P3)."""

import httpx

from metatron.proxy.config import UpstreamConfig
from metatron.proxy.upstream import UpstreamLLMClient


def _sse_body() -> bytes:
    return (
        b'data: {"choices":[{"delta":{"content":"hel"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        b'data: {"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
        b"data: [DONE]\n\n"
    )


async def test_stream_forwards_frames() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test"
        body = request.read()
        assert b'"stream_options"' in body
        return httpx.Response(
            200, content=_sse_body(), headers={"content-type": "text/event-stream"}
        )

    transport = httpx.MockTransport(handler)
    client = UpstreamLLMClient(timeout=5.0, transport=transport)
    cfg = UpstreamConfig(provider="openai", model_name="gpt-4o-mini")
    frames = [
        f
        async for f in client.stream(
            upstream=cfg,
            api_key="sk-test",
            messages=[{"role": "user", "content": "hi"}],
            request_body={
                "model": "gpt-4o-mini",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
            correlation_id="c",
        )
    ]
    raw = b"".join(f.raw for f in frames)
    assert b'"content":"hel"' in raw
    assert frames[0].status == 200
    await client.aclose()


async def test_error_status_exposed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, content=b'{"error":"rate"}')

    transport = httpx.MockTransport(handler)
    client = UpstreamLLMClient(timeout=5.0, transport=transport)
    cfg = UpstreamConfig(provider="openai", model_name="m")
    frames = [
        f
        async for f in client.stream(
            upstream=cfg,
            api_key="k",
            messages=[{"role": "user", "content": "x"}],
            request_body={"model": "m", "messages": []},
            correlation_id="c",
        )
    ]
    assert frames[0].status == 429
    assert b"rate" in b"".join(f.raw for f in frames)
    await client.aclose()
