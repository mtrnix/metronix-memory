"""Cursor-based pagination helpers for MCP tools.

Provides stable pagination for search results using base64-encoded cursors
that preserve query context across pages.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Generic, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class PaginationResult(BaseModel, Generic[T]):
    """Result of a paginated query.

    Attributes:
        items: The items for this page
        has_more: Whether there are more items available
        next_cursor: Cursor to fetch the next page (None if has_more is False)
        total: Total number of items available (if known)
    """

    items: list[T]
    has_more: bool
    next_cursor: str | None = None
    total: int | None = None


def encode_cursor(data: dict[str, Any]) -> str:
    """Encode a dictionary to a base64 cursor string.

    Args:
        data: Dictionary containing pagination context (e.g., offset, page number)

    Returns:
        Base64-encoded cursor string safe for URLs and JSON

    Example:
        >>> cursor = encode_cursor({"offset": 20, "query": "search term"})
        >>> print(cursor)
        eyJvZmZzZXQiOjIwLCJxdWVyeSI6InNlYXJjaCB0ZXJtIn0=
    """
    json_str = json.dumps(data, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a base64 cursor string to a dictionary.

    Args:
        cursor: Base64-encoded cursor string

    Returns:
        Dictionary with pagination context

    Raises:
        ValueError: If cursor is invalid or cannot be decoded

    Example:
        >>> cursor = "eyJvZmZzZXQiOjIwLCJxdWVyeSI6InNlYXJjaCB0ZXJtIn0="
        >>> data = decode_cursor(cursor)
        >>> print(data)
        {'offset': 20, 'query': 'search term'}
    """
    try:
        # Add padding if needed
        padding = 4 - (len(cursor) % 4)
        if padding != 4:
            cursor = cursor + ("=" * padding)

        json_str = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        return json.loads(json_str)
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"Invalid cursor: {cursor}") from e


class CursorPager(Generic[T]):
    """Cursor-based pager for stable pagination.

    Provides consistent pagination across requests by encoding the query
    context in the cursor rather than using offsets.

    Example:
        >>> pager = CursorPager(limit=10)
        >>> result = pager.paginate(items=list(range(25)), cursor=None)
        >>> result.has_more
        True
        >>> result.next_cursor is not None
        True
        >>> result.items
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    """

    def __init__(self, limit: int = 10, max_limit: int = 100):
        """Initialize the cursor pager.

        Args:
            limit: Default number of items per page
            max_limit: Maximum allowed items per page
        """
        self.limit = min(limit, max_limit)
        self.max_limit = max_limit

    def paginate(
        self,
        items: list[T],
        cursor: str | None = None,
        total: int | None = None,
    ) -> PaginationResult[T]:
        """Paginate a list of items.

        Args:
            items: Full list of items to paginate
            cursor: Optional cursor from previous request
            total: Total number of items (if known)

        Returns:
            PaginationResult with items for current page and next cursor
        """
        # Decode cursor to get offset
        offset = 0
        if cursor:
            try:
                cursor_data = decode_cursor(cursor)
                offset = cursor_data.get("offset", 0)
            except ValueError:
                offset = 0

        # Clamp offset to valid range
        offset = min(offset, len(items))

        # Get items for this page
        page_items = items[offset : offset + self.limit]

        # Determine if there are more items
        has_more = offset + self.limit < len(items)

        # Generate next cursor
        next_cursor = None
        if has_more:
            next_cursor = encode_cursor({"offset": offset + self.limit})

        return PaginationResult(
            items=page_items,
            has_more=has_more,
            next_cursor=next_cursor,
            total=total or len(items),
        )

    def create_cursor(self, **kwargs: Any) -> str:
        """Create a cursor with additional context.

        Args:
            **kwargs: Additional context to encode in cursor

        Returns:
            Base64-encoded cursor string

        Example:
            >>> pager = CursorPager(limit=10)
            >>> cursor = pager.create_cursor(query="search term", filters={"type": "doc"})
        """
        return encode_cursor(kwargs)
