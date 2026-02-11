"""Document chunking — root-child pattern from OpenMemory.

Root-child chunking: the first chunk of a document is the "root" and
contains a summary/overview. Subsequent chunks are "children" that
reference the root via parent_id. This allows the retriever to always
include the root chunk for context when any child matches.

Simple chunking: for short documents that don't benefit from the
root-child pattern.
"""

from __future__ import annotations

import re

from metatron.core.models import Chunk, ChunkType

# Sentence-ending pattern: period/question/exclamation followed by
# whitespace or end-of-string. Handles abbreviations poorly but
# good enough for MVP.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

DEFAULT_CHUNK_SIZE = 512
DEFAULT_OVERLAP = 64
ROOT_CHUNK_SIZE = 256


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using regex boundary detection."""
    sentences = _SENTENCE_END.split(text.strip())
    return [s.strip() for s in sentences if s.strip()]


def _token_count_approx(text: str) -> int:
    """Approximate token count (words ≈ 0.75 tokens). Good enough for chunking."""
    return len(text.split())


def _merge_sentences_to_chunks(
    sentences: list[str],
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """Merge sentences into chunks respecting token limits.

    Greedy: add sentences until limit, then start new chunk with overlap.
    Overlap is achieved by re-including the last N tokens worth of sentences.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sent_tokens = _token_count_approx(sentence)

        if current_tokens + sent_tokens > max_tokens and current:
            chunks.append(" ".join(current))

            # Build overlap from the tail of current
            overlap: list[str] = []
            overlap_count = 0
            for s in reversed(current):
                s_tokens = _token_count_approx(s)
                if overlap_count + s_tokens > overlap_tokens:
                    break
                overlap.insert(0, s)
                overlap_count += s_tokens

            current = overlap
            current_tokens = overlap_count

        current.append(sentence)
        current_tokens += sent_tokens

    if current:
        chunks.append(" ".join(current))

    return chunks


def root_child_chunk(
    text: str,
    document_id: str,
    workspace_id: str,
    max_tokens: int = DEFAULT_CHUNK_SIZE,
    overlap_tokens: int = DEFAULT_OVERLAP,
    root_max_tokens: int = ROOT_CHUNK_SIZE,
) -> list[Chunk]:
    """Split text into a root chunk + child chunks (OpenMemory pattern).

    The root chunk contains the opening of the document (up to
    root_max_tokens). All other chunks are children that reference
    the root via parent_id.

    If the document is short enough to fit in one chunk, returns a
    single STANDALONE chunk.

    Args:
        text: Full document text.
        document_id: Parent document ID for all chunks.
        workspace_id: Workspace scope.
        max_tokens: Maximum tokens per child chunk.
        overlap_tokens: Token overlap between consecutive children.
        root_max_tokens: Maximum tokens for the root chunk.

    Returns:
        List of Chunk objects with chunk_type and parent_id set.
    """
    if not text.strip():
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return []

    total_tokens = sum(_token_count_approx(s) for s in sentences)

    # Short document → single standalone chunk
    if total_tokens <= max_tokens:
        return [
            Chunk(
                document_id=document_id,
                workspace_id=workspace_id,
                chunk_type=ChunkType.STANDALONE,
                content=text.strip(),
                token_count=total_tokens,
            )
        ]

    # Build root chunk from leading sentences
    root_sentences: list[str] = []
    root_tokens = 0
    remaining_start = 0

    for i, sentence in enumerate(sentences):
        s_tokens = _token_count_approx(sentence)
        if root_tokens + s_tokens > root_max_tokens and root_sentences:
            remaining_start = i
            break
        root_sentences.append(sentence)
        root_tokens += s_tokens
        remaining_start = i + 1

    root_chunk = Chunk(
        document_id=document_id,
        workspace_id=workspace_id,
        chunk_type=ChunkType.ROOT,
        content=" ".join(root_sentences),
        token_count=root_tokens,
    )

    # Build child chunks from remaining sentences
    remaining = sentences[remaining_start:]
    if not remaining:
        root_chunk.chunk_type = ChunkType.STANDALONE
        return [root_chunk]

    child_texts = _merge_sentences_to_chunks(remaining, max_tokens, overlap_tokens)

    children = [
        Chunk(
            document_id=document_id,
            workspace_id=workspace_id,
            chunk_type=ChunkType.CHILD,
            parent_id=root_chunk.id,
            content=ct,
            token_count=_token_count_approx(ct),
        )
        for ct in child_texts
    ]

    return [root_chunk, *children]


def simple_chunk(
    text: str,
    document_id: str,
    workspace_id: str,
    max_tokens: int = DEFAULT_CHUNK_SIZE,
    overlap_tokens: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Split text into flat standalone chunks (no root-child hierarchy).

    Use for content that doesn't benefit from the root-child pattern
    (e.g., short Jira tickets, chat messages).

    Args:
        text: Full text.
        document_id: Parent document ID.
        workspace_id: Workspace scope.
        max_tokens: Maximum tokens per chunk.
        overlap_tokens: Token overlap between consecutive chunks.

    Returns:
        List of STANDALONE Chunk objects.
    """
    if not text.strip():
        return []

    sentences = _split_sentences(text)
    if not sentences:
        return [
            Chunk(
                document_id=document_id,
                workspace_id=workspace_id,
                chunk_type=ChunkType.STANDALONE,
                content=text.strip(),
                token_count=_token_count_approx(text),
            )
        ]

    chunk_texts = _merge_sentences_to_chunks(sentences, max_tokens, overlap_tokens)

    return [
        Chunk(
            document_id=document_id,
            workspace_id=workspace_id,
            chunk_type=ChunkType.STANDALONE,
            content=ct,
            token_count=_token_count_approx(ct),
        )
        for ct in chunk_texts
    ]


def chunk_text(text: str, max_chars: int = 2500, overlap: int = 200) -> list[str]:
    """Split text into overlapping character-based chunks.

    Simple character-based chunking for backward compatibility with PoC.
    Prefer root_child_chunk() or simple_chunk() for new code.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap

    return chunks
