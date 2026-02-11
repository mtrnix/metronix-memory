"""SimHash near-duplicate detection — from OpenMemory.

SimHash produces a fingerprint of text such that similar texts
have fingerprints with small Hamming distance. This allows efficient
near-duplicate detection without comparing full content.

Algorithm:
1. Tokenize text into shingles (n-grams of words).
2. Hash each shingle to a 64-bit integer.
3. Build a weighted bit vector (sum +1 for set bits, -1 for unset).
4. Final hash: bit i = 1 if vector[i] > 0, else 0.

Two texts are near-duplicates if hamming_distance(h1, h2) <= threshold.
Default threshold: 3 (out of 64 bits).
"""

from __future__ import annotations

import hashlib

SIMHASH_BITS = 64
DEFAULT_SHINGLE_SIZE = 3
DEFAULT_THRESHOLD = 3


def _shingles(text: str, size: int = DEFAULT_SHINGLE_SIZE) -> list[str]:
    """Generate word-level n-gram shingles from text."""
    words = text.lower().split()
    if len(words) < size:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + size]) for i in range(len(words) - size + 1)]


def _hash_shingle(shingle: str) -> int:
    """Hash a shingle to a 64-bit integer using MD5 (truncated)."""
    digest = hashlib.md5(shingle.encode(), usedforsecurity=False).hexdigest()
    return int(digest[:16], 16)


def simhash(text: str, shingle_size: int = DEFAULT_SHINGLE_SIZE) -> int:
    """Compute the 64-bit SimHash fingerprint of text.

    Args:
        text: Input text.
        shingle_size: Number of words per shingle.

    Returns:
        64-bit integer fingerprint.
    """
    if not text.strip():
        return 0

    vector = [0] * SIMHASH_BITS
    shingle_list = _shingles(text, shingle_size)

    for shingle in shingle_list:
        h = _hash_shingle(shingle)
        for i in range(SIMHASH_BITS):
            if h & (1 << i):
                vector[i] += 1
            else:
                vector[i] -= 1

    fingerprint = 0
    for i in range(SIMHASH_BITS):
        if vector[i] > 0:
            fingerprint |= 1 << i

    return fingerprint


def hamming_distance(hash1: int, hash2: int) -> int:
    """Count the number of differing bits between two hashes.

    Args:
        hash1: First SimHash fingerprint.
        hash2: Second SimHash fingerprint.

    Returns:
        Number of bit positions where the hashes differ (0-64).
    """
    xor = hash1 ^ hash2
    return bin(xor).count("1")


def is_near_duplicate(
    hash1: int,
    hash2: int,
    threshold: int = DEFAULT_THRESHOLD,
) -> bool:
    """Check if two SimHash fingerprints indicate near-duplicate content.

    Args:
        hash1: First SimHash fingerprint.
        hash2: Second SimHash fingerprint.
        threshold: Maximum Hamming distance to consider as duplicate.

    Returns:
        True if the texts are likely near-duplicates.
    """
    return hamming_distance(hash1, hash2) <= threshold
