"""Context assembly — root-child linking for LLM prompt building.

When a child chunk is retrieved, we fetch its root chunk and prepend
it to provide the LLM with document-level context. This is the
retrieval counterpart to the root-child chunking strategy.
"""

from __future__ import annotations

import structlog

from metronix.core.models import Chunk, ChunkType

logger = structlog.get_logger()


def assemble_context(
    chunks: list[Chunk],
    all_chunks_by_id: dict[str, Chunk] | None = None,
    max_context_tokens: int = 4096,
) -> str:
    """Assemble final context string from retrieved chunks.

    For CHILD chunks: prepend the ROOT chunk content (if available).
    For ROOT/STANDALONE chunks: include as-is.
    Deduplicates roots that would appear multiple times.
    Respects token budget.

    Args:
        chunks: Ranked list of retrieved chunks.
        all_chunks_by_id: Lookup dict for root chunks. If None,
            child chunks are included without root context.
        max_context_tokens: Approximate token budget for the context.

    Returns:
        Assembled context string ready for LLM prompt.
    """
    logger.info("context.assemble", chunk_count=len(chunks))

    seen_roots: set[str] = set()
    parts: list[str] = []
    total_tokens = 0

    for chunk in chunks:
        # If this is a child, try to prepend its root
        if (
            chunk.chunk_type == ChunkType.CHILD
            and chunk.parent_id
            and all_chunks_by_id
            and chunk.parent_id not in seen_roots
        ):
            root = all_chunks_by_id.get(chunk.parent_id)
            if root:
                if total_tokens + root.token_count > max_context_tokens:
                    break
                parts.append(f"[Context: {root.content}]")
                total_tokens += root.token_count
                seen_roots.add(chunk.parent_id)

        if total_tokens + chunk.token_count > max_context_tokens:
            break

        parts.append(chunk.content)
        total_tokens += chunk.token_count

    return "\n\n---\n\n".join(parts)
