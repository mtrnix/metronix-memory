"""OpenAI-compatible API — /v1/models and /v1/chat/completions.

Allows Open WebUI (and any OpenAI-compatible client) to use Metatron
as an LLM backend. Wraps the existing hybrid search pipeline into
the OpenAI Chat Completions format.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from metatron.core.config import Settings

logger = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["openai-compat"])

MODEL_PREFIX = "metatron-rag-"


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def verify_openai_compat_key(request: Request) -> None:
    """Validate API key — personal key or static fallback."""
    settings: Settings = request.app.state.settings
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing API key")

    raw_key = auth[7:]
    api_key_store = getattr(request.app.state, "api_key_store", None)

    if api_key_store is not None:
        resolved = await api_key_store.resolve_key(
            raw_key, static_key=settings.openai_compat_key
        )
        if resolved is not None:
            request.state.openai_user_id = resolved["user_id"]
            request.state.openai_key_source = resolved["source"]
            return

    # Fallback: legacy static key check (no api_key_store available)
    import hmac
    expected = settings.openai_compat_key
    if expected and hmac.compare_digest(raw_key, expected):
        request.state.openai_user_id = "openai-default"
        request.state.openai_key_source = "static"
        return

    raise HTTPException(status_code=401, detail="Invalid API key")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str
    content: str = ""


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[ChatMessage]
    stream: bool = False
    user: str | None = None


# ---------------------------------------------------------------------------
# Conversation history — extracted from req.messages (no in-memory store)
# ---------------------------------------------------------------------------

_MAX_HISTORY_CHARS = 4000


def _build_composite_query(
    messages: list[ChatMessage],
    question: str,
    history_turns: int = 6,
) -> str:
    """Build composite query from previous user messages in the conversation.

    Takes the last `history_turns` user messages from the OpenAI-format
    messages list (sent by Open WebUI) instead of maintaining a separate
    in-memory history store.
    """
    previous = [m.content for m in messages if m.role == "user" and m.content != question]
    previous = previous[-history_turns:]

    history_lines: list[str] = []
    total_chars = 0
    for msg in reversed(previous):
        line = f"Previous question: {msg[:500]}"
        if total_chars + len(line) > _MAX_HISTORY_CHARS:
            break
        history_lines.insert(0, line)
        total_chars += len(line)

    if history_lines:
        return "\n".join(history_lines + [f"Current question: {question}"])
    return question


# ---------------------------------------------------------------------------
# Source formatting
# ---------------------------------------------------------------------------

_INLINE_REF_RE = re.compile(r"\[\$\[(.+?)\]\$\]")
_KNOWN_EXT_RE = re.compile(
    r"\.(pdf|txt|md|docx?|xlsx?|csv|json|html|xml|yml|yaml|pptx?|rtf)$",
    re.IGNORECASE,
)


@dataclass
class _ParsedSource:
    title: str
    url: str | None


def _parse_source(raw: str) -> _ParsedSource:
    """Parse raw source line like '📄 Title — URL' into title + url."""
    # Skip leading emoji (first codepoint + whitespace)
    chars = list(raw)
    rest = raw[len(chars[0]) :].strip() if chars else raw
    dash_idx = rest.rfind(" \u2014 ")
    if dash_idx >= 0:
        return _ParsedSource(
            title=rest[:dash_idx].strip(),
            url=rest[dash_idx + 3 :].strip(),
        )
    return _ParsedSource(title=rest, url=None)


def _strip_ext(s: str) -> str:
    return _KNOWN_EXT_RE.sub("", s).strip()


def _match_inline_source(
    ref_text: str,
    sources: list[_ParsedSource],
) -> _ParsedSource | None:
    """Match reference marker text to a source using 4-level matching.

    Mirrors frontend matchInlineSource() logic:
    1. Exact match (case-insensitive)
    2. Substring match (with 40% length threshold)
    3. Exact match without file extensions
    4. Substring match without file extensions (with 40% threshold)
    """
    norm = ref_text.lower().strip()
    norm_no_ext = _strip_ext(norm)

    def _substr(a: str, b: str) -> bool:
        """Check if a contains b or b contains a (with 40% length ratio)."""
        if len(a) < 3 or len(b) < 3:
            return False
        if a in b:
            return True
        return b in a and len(a) / len(b) >= 0.4

    # Level 1: exact
    for s in sources:
        if s.title.lower() == norm:
            return s
    # Level 2: substring
    for s in sources:
        if _substr(s.title.lower(), norm):
            return s
    # Level 3: exact without extensions
    for s in sources:
        if _strip_ext(s.title.lower()) == norm_no_ext:
            return s
    # Level 4: substring without extensions
    for s in sources:
        if _substr(_strip_ext(s.title.lower()), norm_no_ext):
            return s
    return None


def _resolve_reference_markers(text: str, sources: list[str]) -> str:
    """Replace [$[title]$] markers with [title](url) markdown links.

    Uses the same 4-level matching algorithm as the admin frontend.
    """
    parsed = [_parse_source(s) for s in sources]

    def _replace(m: re.Match) -> str:
        ref_text = m.group(1)
        source = _match_inline_source(ref_text, parsed)
        if not source:
            return ref_text
        if source.url:
            return f"[{source.title}]({source.url})"
        return source.title

    return _INLINE_REF_RE.sub(_replace, text)


_DISPLAY_SOURCES_LIMIT = 5


def _sources_to_markdown(sources: list[str], limit: int = _DISPLAY_SOURCES_LIMIT) -> str:
    """Convert source lines from 'icon Title — URL' to markdown links.

    Only the first *limit* sources are rendered in the footer block shown to
    the user.  The full list is still used by ``_resolve_reference_markers``
    so that every ``[$[title]$]`` inline reference can be resolved to a URL.
    """
    if not sources:
        return ""
    md_lines: list[str] = []
    for source in sources[:limit]:
        if " \u2014 " in source:
            label, _, url = source.partition(" \u2014 ")
            md_lines.append(f"- [{label.strip()}]({url.strip()})")
        else:
            md_lines.append(f"- {source}")
    return "\n\n---\n**Sources:**\n" + "\n".join(md_lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_workspace_id(model: str) -> str | None:
    """Extract workspace_id from model id like 'metatron-rag-MTRNIX'."""
    if model.startswith(MODEL_PREFIX):
        return model[len(MODEL_PREFIX) :]
    return None


def _openai_error(
    status: int,
    message: str,
    error_type: str = "invalid_request_error",
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": error_type}},
    )


# ---------------------------------------------------------------------------
# GET /v1/openapi.json — stub for Open WebUI connection verification
# ---------------------------------------------------------------------------


@router.get("/openapi.json")
async def openapi_stub() -> dict:
    """Minimal OpenAPI spec stub so Open WebUI accepts the connection."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Metatron OpenAI-compatible API", "version": "0.1.0"},
        "paths": {},
    }


# ---------------------------------------------------------------------------
# GET /v1/models
# ---------------------------------------------------------------------------


@router.get("/models", dependencies=[Depends(verify_openai_compat_key)])
async def list_models(request: Request) -> dict:
    """List available models (one per workspace)."""
    from metatron.workspaces import get_workspace_manager

    manager = get_workspace_manager()
    workspaces = manager.list_workspaces()
    now = int(time.time())

    models = []
    for ws in workspaces:
        created = now
        if ws.created_at:
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(ws.created_at)
                created = int(dt.timestamp())
            except (ValueError, TypeError):
                pass
        models.append(
            {
                "id": f"{MODEL_PREFIX}{ws.workspace_id}",
                "name": ws.name or ws.workspace_id,
                "object": "model",
                "created": created,
                "owned_by": "metatron",
            }
        )

    return {"object": "list", "data": models}


# ---------------------------------------------------------------------------
# Streaming generator
# ---------------------------------------------------------------------------


async def _stream_response(
    composite_query: str,
    user_message: str,
    workspace_id: str,
    user_id: str,
    model: str,
    completion_id: str,
    created: int,
    plugin_manager: object | None = None,
) -> AsyncGenerator[str, None]:
    """Generate OpenAI-format SSE stream from search pipeline."""
    import asyncio

    from metatron.api.routes.chat import extract_sources_section, split_into_sentences

    def _chunk(delta: dict, finish_reason: str | None = None) -> str:
        data = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    # Role chunk
    yield _chunk({"role": "assistant"})

    # Run search pipeline
    try:
        from metatron.retrieval.search import hybrid_search_and_answer

        answer = await hybrid_search_and_answer(
            query=composite_query,
            user_id=user_id,
            workspace_id=workspace_id,
            intent_query=user_message,
            plugin_manager=plugin_manager,
        )
    except Exception as exc:
        logger.error("openai_compat.stream.error", error=str(exc), exc_info=True)
        yield _chunk({"content": "An error occurred while processing your request."})
        yield _chunk({}, "stop")
        yield "data: [DONE]\n\n"
        return

    # Parse sources and convert to markdown
    body, sources = extract_sources_section(answer)
    body = _resolve_reference_markers(body, sources)
    final_content = body + _sources_to_markdown(sources)

    # Stream answer in sentence chunks
    for sentence in split_into_sentences(final_content):
        yield _chunk({"content": sentence})
        await asyncio.sleep(0.03)

    # Finish
    yield _chunk({}, "stop")
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# POST /v1/chat/completions
# ---------------------------------------------------------------------------


@router.post("/chat/completions", dependencies=[Depends(verify_openai_compat_key)])
async def chat_completions(req: ChatCompletionRequest, request: Request):
    """OpenAI-compatible chat completions endpoint."""
    from metatron.workspaces import get_workspace_manager

    # Validate messages
    if not req.messages:
        return _openai_error(400, "Messages required")

    # Find last user message
    user_message = None
    for msg in reversed(req.messages):
        if msg.role == "user":
            user_message = msg.content
            break
    if not user_message:
        return _openai_error(400, "No user message found")

    # Parse workspace from model id
    workspace_id = _parse_workspace_id(req.model)
    if not workspace_id:
        return _openai_error(404, f"Model not found: {req.model}")

    manager = get_workspace_manager()
    if not manager.get_workspace(workspace_id):
        return _openai_error(404, f"Model not found: {req.model}")

    user_id = getattr(request.state, "openai_user_id", None) or req.user or "openai-default"
    completion_id = f"chatcmpl-{uuid4().hex[:24]}"
    created = int(time.time())
    plugin_manager = getattr(request.app.state, "plugin_manager", None)

    # Build composite query from conversation messages
    composite_query = _build_composite_query(req.messages, user_message)

    if req.stream:
        return StreamingResponse(
            _stream_response(
                composite_query,
                user_message,
                workspace_id,
                user_id,
                req.model,
                completion_id,
                created,
                plugin_manager,
            ),
            media_type="text/event-stream",
        )

    # Non-streaming path
    try:
        from metatron.retrieval.search import hybrid_search_and_answer

        answer = await hybrid_search_and_answer(
            query=composite_query,
            user_id=user_id,
            workspace_id=workspace_id,
            intent_query=user_message,
            plugin_manager=plugin_manager,
        )
    except Exception as exc:
        logger.error("openai_compat.search_error", error=str(exc), exc_info=True)
        return _openai_error(500, "Internal error", "server_error")

    # Convert sources to markdown
    from metatron.api.routes.chat import extract_sources_section

    body, sources = extract_sources_section(answer)
    body = _resolve_reference_markers(body, sources)
    final_content = body + _sources_to_markdown(sources)

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": final_content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
