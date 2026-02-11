"""Platform user mapping — resolves channel identities to internal users.

When a message arrives from Telegram or Slack, we need to map the
platform user ID to an internal User object. This module handles
that lookup and optional auto-creation.
"""

from __future__ import annotations

import structlog

from metatron.core.models import User
from metatron.storage.postgres import PostgresStore

logger = structlog.get_logger()


async def map_platform_user(
    channel: str,
    channel_user_id: str,
    store: PostgresStore,
    auto_create: bool = True,
) -> User | None:
    """Map a platform identity to an internal user.

    Looks up the user by channel + channel_user_id in the user_mappings
    table. If not found and auto_create is True, creates a new user
    with viewer role.

    Args:
        channel: Platform name ("telegram", "slack").
        channel_user_id: Platform-specific user identifier.
        store: Database store for user lookups.
        auto_create: If True, create user on first contact.

    Returns:
        Internal User object, or None if not found and auto_create=False.
    """
    logger.info(
        "auth.user_mapping.lookup",
        channel=channel,
        channel_user_id=channel_user_id,
    )
    # TODO: implement user mapping
    # 1. SELECT user_id FROM user_platform_mappings
    #    WHERE channel = $1 AND channel_user_id = $2
    # 2. If found: return await store.get_user(user_id)
    # 3. If not found and auto_create:
    #    a. Create User(username=f"{channel}_{channel_user_id}", role=VIEWER)
    #    b. Insert mapping row
    #    c. Return new user
    # 4. If not found and not auto_create: return None
    raise NotImplementedError("User mapping not yet implemented")
