"""
BM25 Sparse Vector generation for Qdrant hybrid search.

BM25 (Best Matching 25) is a ranking function used in information retrieval.
This module generates sparse vectors compatible with Qdrant's sparse vector search.

Migrated from PoC: metatron_experiments/metatron/indexers/bm25.py
"""

import re
from collections import Counter

import structlog

logger = structlog.get_logger()

# Default vocabulary size for consistent hashing (use large prime for less collisions)
DEFAULT_VOCAB_SIZE = 30000


# Simple tokenizer that handles English and transliterated text
def tokenize(text: str) -> list[str]:
    """
    Tokenize text into words.
    Handles English text, removes punctuation, lowercases.
    """
    # Lowercase
    text = text.lower()
    # Remove special characters, keep only alphanumeric and spaces
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Split into words
    words = text.split()
    # Filter short words and stopwords
    stopwords = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "was",
        "are",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "they",
        "them",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "also",
        "now",
        "here",
        "there",
        "then",
        "once",
    }
    return [w for w in words if len(w) > 2 and w not in stopwords]


def word_to_index(word: str, vocab_size: int = DEFAULT_VOCAB_SIZE) -> int:
    """Convert word to index using hash."""
    return hash(word) % vocab_size


def compute_bm25_sparse_vector(
    text: str,
    k1: float = 1.5,
    b: float = 0.75,
    avgdl: float = 256.0,
    vocab_size: int = DEFAULT_VOCAB_SIZE,
) -> tuple[list[int], list[float]]:
    """
    Compute BM25 sparse vector for a document.

    Args:
        text: Document text
        k1: Term frequency saturation parameter (default 1.5)
        b: Length normalization parameter (default 0.75)
        avgdl: Average document length (default 256 tokens)
        vocab_size: Vocabulary size for hashing (default 30000)

    Returns:
        Tuple of (indices, values) for sparse vector
    """
    tokens = tokenize(text)
    if not tokens:
        return [], []

    doc_len = len(tokens)
    term_freqs = Counter(tokens)

    indices = []
    values = []

    # Use dict to aggregate values for hash collisions
    index_values: dict[int, float] = {}

    for term, freq in term_freqs.items():
        # BM25 term frequency component
        tf_component = (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * doc_len / avgdl))

        # We don't have IDF (corpus-level), so use just TF component
        # IDF would require knowing document frequencies across all docs
        # For sparse vectors, TF is sufficient for keyword matching

        idx = word_to_index(term, vocab_size)
        # Aggregate values if hash collision (different words -> same index)
        index_values[idx] = index_values.get(idx, 0.0) + float(tf_component)

    indices = list(index_values.keys())
    values = list(index_values.values())

    return indices, values


def compute_query_sparse_vector(
    query: str,
    vocab_size: int = DEFAULT_VOCAB_SIZE,
) -> tuple[list[int], list[float]]:
    """
    Compute sparse vector for a query.
    Queries use simpler weighting (just presence).

    Args:
        query: Search query
        vocab_size: Vocabulary size for hashing (default 30000)

    Returns:
        Tuple of (indices, values) for sparse vector
    """
    tokens = tokenize(query)
    if not tokens:
        return [], []

    # For queries, we just use term presence with equal weights
    term_freqs = Counter(tokens)

    # Use dict to aggregate values for hash collisions
    index_values: dict[int, float] = {}

    for term, freq in term_freqs.items():
        idx = word_to_index(term, vocab_size)
        # Query terms all get weight 1.0 (or freq if repeated)
        # Aggregate values if hash collision
        index_values[idx] = index_values.get(idx, 0.0) + float(freq)

    indices = list(index_values.keys())
    values = list(index_values.values())

    return indices, values


# For Qdrant SparseVector format
def to_qdrant_sparse(indices: list[int], values: list[float]) -> dict:
    """Convert to Qdrant SparseVector format."""
    return {"indices": indices, "values": values}
