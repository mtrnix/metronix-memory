"""One-time migration: env-var-based connector/channel config → DB connections.

Reads legacy environment variables (CONFLUENCE_URL, TELEGRAM_BOT_TOKEN, etc.),
groups them by connector type, validates, and creates encrypted DB connections
via PostgresStore.create_connection(). Idempotent — skips types that already
exist in the database.

Called automatically at app startup (after Alembic migrations, before channel
manager). Safe to run repeatedly.
"""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Env var → (connector_type, config_field_name) mapping
#
# Names match the aliases that were formerly in core/config.py Settings.
# ---------------------------------------------------------------------------

_ENV_MAPPINGS: dict[str, tuple[str, str]] = {
    # Confluence
    "CONFLUENCE_URL": ("confluence", "url"),
    "CONFLUENCE_USERNAME": ("confluence", "username"),
    "CONFLUENCE_API_TOKEN": ("confluence", "api_token"),
    "CONFLUENCE_SPACE_KEY": ("confluence", "space_key"),
    # Jira
    "JIRA_URL": ("jira", "url"),
    "JIRA_USERNAME": ("jira", "username"),
    "JIRA_API_TOKEN": ("jira", "api_token"),
    "JIRA_PROJECT_KEY": ("jira", "project_key"),
    # Notion
    "NOTION_API_TOKEN": ("notion", "api_token"),
    # Telegram
    "TELEGRAM_BOT_TOKEN": ("telegram", "bot_token"),
    # Discord
    "DISCORD_BOT_TOKEN": ("discord", "bot_token"),
    # Slack
    "SLACK_BOT_TOKEN": ("slack", "bot_token"),
    "SLACK_APP_TOKEN": ("slack", "app_token"),
    "SLACK_SIGNING_SECRET": ("slack", "signing_secret"),
}


def _collect_configs_from_env() -> dict[str, dict[str, str]]:
    """Read env vars and group values by connector type.

    Returns ``{connector_type: {field_name: value, ...}}`` for types
    where at least one env var is set to a non-empty string.
    """
    configs: dict[str, dict[str, str]] = {}
    for env_name, (ctype, field) in _ENV_MAPPINGS.items():
        value = os.environ.get(env_name, "").strip()
        if value:
            configs.setdefault(ctype, {})[field] = value
    return configs


async def migrate_env_to_db(
    postgres_dsn: str,
    workspace_id: str,
    fernet_key: str,
) -> dict[str, list[str]]:
    """Migrate legacy env-var credentials into encrypted DB connections.

    Idempotent: if a connection of the same connector_type already exists
    for the workspace, it is skipped.

    Args:
        postgres_dsn: Async PostgreSQL DSN.
        workspace_id: Target workspace for created connections.
        fernet_key: Fernet key for encrypting stored config.

    Returns:
        ``{"created": [...], "skipped": [...], "errors": [...]}``
    """
    from metronix.connectors.schemas import CONNECTOR_SCHEMAS, validate_config
    from metronix.storage.postgres import PostgresStore

    result: dict[str, list[str]] = {
        "created": [],
        "skipped": [],
        "errors": [],
    }

    if not fernet_key:
        logger.warning("migrate_env.no_fernet_key")
        return result

    configs = _collect_configs_from_env()
    if not configs:
        return result

    store = PostgresStore(postgres_dsn)
    try:
        # Fetch existing connections to check for duplicates
        existing = await store.list_connections(workspace_id, fernet_key)
        existing_types = {c["connector_type"] for c in existing}

        for ctype, config in configs.items():
            # Already migrated?
            if ctype in existing_types:
                logger.info(
                    "migrate_env.skip_existing",
                    connector_type=ctype,
                )
                result["skipped"].append(ctype)
                continue

            # Validate required fields
            errors = validate_config(ctype, config)
            if errors:
                logger.warning(
                    "migrate_env.incomplete_config",
                    connector_type=ctype,
                    errors=errors,
                )
                result["skipped"].append(ctype)
                continue

            # Determine friendly name from schema
            schema = CONNECTOR_SCHEMAS.get(ctype)
            name = schema.label if schema else ctype.capitalize()

            try:
                await store.create_connection(
                    workspace_id=workspace_id,
                    connector_type=ctype,
                    name=name,
                    config=config,
                    fernet_key=fernet_key,
                )
                logger.info(
                    "migrate_env.created",
                    connector_type=ctype,
                    name=name,
                )
                result["created"].append(ctype)
            except Exception as exc:
                logger.error(
                    "migrate_env.create_failed",
                    connector_type=ctype,
                    error=str(exc),
                )
                result["errors"].append(ctype)
    finally:
        await store.close()

    return result
