"""
Embedding Proxy Service

OpenAI-compatible proxy for Ollama embeddings.
Translates requests from OpenAI format to Ollama format.
Supports both float and base64 encoding formats.
Handles empty/whitespace-only input strings gracefully.
"""

import base64
import logging
import os
import struct
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nomic-embed-text")
OLLAMA_EMBEDDINGS_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/embeddings"

logger.info("Embedding Proxy Configuration:")
logger.info("  Ollama Host: %s", OLLAMA_HOST)
logger.info("  Ollama Port: %s", OLLAMA_PORT)
logger.info("  Ollama Model: %s", OLLAMA_MODEL)
logger.info("  Ollama URL: %s", OLLAMA_EMBEDDINGS_URL)

# Embedding dimension (detected on first real request, fallback 768)
_EMBEDDING_DIM: int | None = None


# ============================================================================
# OpenAI API Models (Request/Response)
# ============================================================================


class EmbeddingRequest(BaseModel):
    """OpenAI-compatible embedding request."""

    input: str | list[str] = Field(..., description="Text or list of texts")
    model: str = Field(..., description="Model for embeddings")
    encoding_format: str = Field(default="float", description="Encoding format")


class EmbeddingUsage(BaseModel):
    """Token usage information."""

    prompt_tokens: int
    total_tokens: int


# ============================================================================
# Ollama Client
# ============================================================================


class OllamaClient:
    """Client for Ollama API."""

    def __init__(self, url: str, model: str, timeout: float = 30.0):
        self.url = url
        self.model = model
        self.timeout = timeout
        logger.info("OllamaClient initialized: %s, model=%s", url, model)

    async def get_embedding(self, text: str) -> list[float]:
        """Get embedding for a single text from Ollama."""
        request_body = {"model": self.model, "prompt": text}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.url,
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                )

            if response.status_code == 200:
                data = response.json()
                embedding = data.get("embedding", [])
                if not embedding:
                    raise HTTPException(
                        status_code=500,
                        detail="Ollama returned empty embedding",
                    )
                return embedding
            else:
                logger.error("Ollama API error: %s - %s", response.status_code, response.text)
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Ollama API error: {response.text}",
                )

        except httpx.TimeoutException:
            logger.error("Timeout calling Ollama API")
            raise HTTPException(status_code=504, detail="Timeout calling Ollama API") from None
        except httpx.ConnectError as e:
            logger.error("Connection error to Ollama: %s", e)
            raise HTTPException(
                status_code=503,
                detail=f"Cannot connect to Ollama at {self.url}",
            ) from e
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            raise HTTPException(status_code=500, detail=f"Internal error: {e!s}") from e


# ============================================================================
# Helpers
# ============================================================================


def _encode_base64(embedding: list[float]) -> str:
    """Encode a float embedding list as base64 (little-endian float32)."""
    packed = struct.pack(f"<{len(embedding)}f", *embedding)
    return base64.b64encode(packed).decode("ascii")


async def _get_embedding_dim(client: "OllamaClient") -> int:
    """Detect embedding dimension by probing Ollama with a dummy text."""
    global _EMBEDDING_DIM
    if _EMBEDDING_DIM is not None:
        return _EMBEDDING_DIM
    try:
        probe = await client.get_embedding("dimension probe")
        _EMBEDDING_DIM = len(probe)
    except Exception:
        _EMBEDDING_DIM = 768  # fallback for nomic-embed-text
    return _EMBEDDING_DIM


# ============================================================================
# FastAPI Application
# ============================================================================

ollama_client: OllamaClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI."""
    global ollama_client
    logger.info("Starting Embedding Proxy Service...")
    ollama_client = OllamaClient(url=OLLAMA_EMBEDDINGS_URL, model=OLLAMA_MODEL, timeout=30.0)
    logger.info("Embedding Proxy Service started")
    yield
    logger.info("Shutting down Embedding Proxy Service...")


app = FastAPI(
    title="Embedding Proxy",
    description="OpenAI-compatible proxy for Ollama embeddings",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "embedding-proxy",
        "ollama_url": OLLAMA_EMBEDDINGS_URL,
        "ollama_model": OLLAMA_MODEL,
    }


@app.post("/v1/embeddings")
@app.post("/embeddings")
async def create_embeddings(request: EmbeddingRequest):
    """OpenAI-compatible endpoint for creating embeddings.

    Handles:
    - Both ``/v1/embeddings`` and ``/embeddings`` paths.
    - ``encoding_format`` of ``float`` (default) and ``base64``.
    - Empty / whitespace-only input strings → zero vector.
    """
    start_time = time.time()
    use_base64 = request.encoding_format == "base64"

    # Normalize input to list
    texts = [request.input] if isinstance(request.input, str) else list(request.input)

    logger.info(
        "Creating embeddings for %d text(s), model=%s, format=%s",
        len(texts),
        request.model,
        request.encoding_format,
    )

    try:
        data_items: list[dict] = []

        for idx, text in enumerate(texts):
            # Handle empty / whitespace-only strings
            if not text or not text.strip():
                dim = await _get_embedding_dim(ollama_client)
                emb = [0.0] * dim
                logger.debug("Empty text at index %d → zero vector (dim=%d)", idx, dim)
            else:
                emb = await ollama_client.get_embedding(text)

            if use_base64:
                data_items.append(
                    {"object": "embedding", "embedding": _encode_base64(emb), "index": idx}
                )
            else:
                data_items.append({"object": "embedding", "embedding": emb, "index": idx})

        total_tokens = sum(len(t.split()) for t in texts if t)

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Created %d embeddings in %.2fms (avg %.2fms each)",
            len(data_items),
            elapsed_ms,
            elapsed_ms / max(len(data_items), 1),
        )

        return {
            "object": "list",
            "data": data_items,
            "model": OLLAMA_MODEL,
            "usage": {"prompt_tokens": total_tokens, "total_tokens": total_tokens},
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating embeddings: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e!s}") from e


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "embedding-proxy",
        "version": "1.0.0",
        "endpoints": {"health": "/health", "embeddings": "/v1/embeddings"},
        "ollama": {"host": OLLAMA_HOST, "port": OLLAMA_PORT, "model": OLLAMA_MODEL},
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PROXY_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
