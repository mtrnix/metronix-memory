"""Entity Resolver - core functions for resolving entity synonyms.

Uses:
- rapidfuzz for typo detection (> 90% match)
- Ollama embeddings for semantic similarity (> 0.88)

Env variables:
- ENABLE_SEMANTIC_MATCHING=true/false (default: true)
"""

import math
import os
import re

import structlog
from rapidfuzz import fuzz

logger = structlog.get_logger()

# Semantic matching enabled by default (uses Ollama, already running)
ENABLE_SEMANTIC_MATCHING = os.getenv("ENABLE_SEMANTIC_MATCHING", "true").lower() == "true"

# Minimal nickname map (extend for your domain)
_NICKNAME_MAP = {
    # EN
    "kostya": "konstantin",
    # RU
    "\u043a\u043e\u0441\u0442\u044f": "\u043a\u043e\u043d\u0441\u0442\u0430\u043d\u0442\u0438\u043d",
}


def _is_person_type(entity_type: str | None) -> bool:
    return (entity_type or "").strip().lower() in {
        "person",
        "human",
        "employee",
        "user",
    }


def _tokenize_name(name: str) -> list[str]:
    """Tokenize a name into normalized tokens.

    - Keeps words from parentheses as tokens
    - Removes punctuation
    - Applies a small nickname map
    """
    s = (name or "").strip().lower()
    if not s:
        return []

    # Keep alnum/space/hyphen/parentheses, drop other punctuation
    s = re.sub(r"[^\w\s()\-]", " ", s, flags=re.UNICODE)
    # Convert parentheses to spaces (keep contents)
    s = s.replace("(", " ").replace(")", " ")
    s = " ".join(s.split())

    tokens = [t for t in re.split(r"[\s\-]+", s) if t]
    tokens = [_NICKNAME_MAP.get(t, t) for t in tokens]
    return tokens


def _normalize_entity_name(name: str) -> str:
    """Normalize entity names for robust matching."""
    return " ".join(_tokenize_name(name))


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)


def find_typo_match(
    name: str,
    existing: list[str],
    threshold: float = 90,
    entity_type: str | None = None,
) -> str | None:
    """Find a typo match via rapidfuzz.

    Returns the name of an existing entity if match > threshold.
    """
    if not existing:
        return None

    # Person heuristic: avoid risky merges for single-token names.
    if _is_person_type(entity_type):
        in_tokens = _tokenize_name(name)
        if len(in_tokens) == 1:
            t = in_tokens[0]
            candidates = []
            for ex in existing:
                ex_tokens = _tokenize_name(ex)
                if t in ex_tokens and len(ex_tokens) >= 2:
                    candidates.append(ex)
            if len(candidates) == 1:
                logger.debug(
                    "person_short_name_match",
                    name=name,
                    match=candidates[0],
                )
                return candidates[0]
            return None

    best_match = None
    best_score = 0
    norm_name = _normalize_entity_name(name)

    for existing_name in existing:
        norm_existing = _normalize_entity_name(existing_name)
        if not norm_existing or not norm_name:
            continue
        score = max(
            fuzz.ratio(norm_name, norm_existing),
            fuzz.token_sort_ratio(norm_name, norm_existing),
            fuzz.token_set_ratio(norm_name, norm_existing),
        )
        if score > best_score:
            best_score = score
            best_match = existing_name

    if best_score >= threshold:
        logger.debug(
            "typo_match_found",
            name=name,
            match=best_match,
            score=best_score,
        )
        return best_match

    return None


def find_semantic_match(
    name: str,
    existing: list[str],
    threshold: float = 0.88,
) -> str | None:
    """Find a semantically similar entity via Ollama embeddings.

    Returns the name if cosine similarity > threshold.
    """
    if not ENABLE_SEMANTIC_MATCHING:
        return None
    if not existing:
        return None

    # Skip semantic matching if too many candidates (performance)
    if len(existing) > 50:
        logger.debug(
            "semantic_match_skipped",
            name=name,
            candidate_count=len(existing),
        )
        return None

    try:
        from metatron.llm.embeddings import get_cached_embedding

        logger.debug("getting_embedding", name=name)
        name_emb = get_cached_embedding(name)
        logger.debug(
            "comparing_embeddings",
            name=name,
            candidate_count=len(existing),
        )

        best_match = None
        best_score = 0.0

        for existing_name in existing:
            existing_emb = get_cached_embedding(existing_name)
            score = cosine_similarity(name_emb, existing_emb)
            if score > best_score:
                best_score = score
                best_match = existing_name

        if best_score >= threshold:
            logger.debug(
                "semantic_match_found",
                name=name,
                match=best_match,
                score=round(best_score, 3),
            )
            return best_match

    except Exception as e:
        logger.warning("semantic_matching_error", name=name, error=str(e))
        return None

    return None
