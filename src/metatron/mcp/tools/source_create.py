"""MCP tool: metatron_source_create — create a data-source connection."""

from __future__ import annotations

from typing import Any

from metatron.mcp.errors import handle_tool_error
from metatron.mcp.server import mcp


@mcp.tool(
    description=(
        "Create a new data source (connection). Call metatron_source_schemas "
        "first to learn the required config fields.\n\n"
        "**Parameters:**\n"
        "- connector_type: confluence | jira | notion (working). github | gdrive "
        "| slack_history are accepted but NOT implemented — sync will fail.\n"
        "- name: human-friendly label\n"
        "- config: connector config dict (e.g. url, username, api_token)\n"
        "- workspace_id: target workspace (optional, defaults to 'default')\n\n"
        "Channels (telegram/discord/slack) are rejected. The new source is "
        "auto-scheduled for nightly sync; trigger an immediate sync with "
        "metatron_source_sync.\n\n"
        "**Returns:** the created source with masked secrets."
    ),
)
async def metatron_source_create(
    connector_type: str,
    name: str,
    config: dict[str, Any],
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Create a data-source connection."""
    try:
        from metatron.connectors.connection_sync import ensure_workspace_exists
        from metatron.connectors.schemas import CONNECTOR_SCHEMAS, validate_config
        from metatron.mcp.tools._source_deps import resolve
        from metatron.mcp.tools.models import SourceDTO

        schema = CONNECTOR_SCHEMAS.get(connector_type)
        if schema is None:
            available = sorted(
                t for t, s in CONNECTOR_SCHEMAS.items() if s.category == "connector"
            )
            raise ValueError(f"Unknown connector type '{connector_type}'. Available: {available}")
        if schema.category != "connector":
            raise ValueError(
                f"'{connector_type}' is a channel, not a data source. "
                "Source tools manage connectors only."
            )

        errors = validate_config(connector_type, config)
        if errors:
            raise ValueError("; ".join(errors))

        ws_id, store, fernet_key = resolve(workspace_id)
        await ensure_workspace_exists(store, ws_id)
        result = await store.create_connection(
            workspace_id=ws_id,
            connector_type=connector_type,
            name=name,
            config=config,
            fernet_key=fernet_key,
        )
        # Re-fetch so sync_cron/next_run_at match the DB row (create_connection
        # returns sync_cron=None even though the DB default applies).
        fresh = await store.get_connection(result["id"], fernet_key)
        return SourceDTO(**(fresh or result)).model_dump()
    except Exception as e:
        return {"error": handle_tool_error("metatron_source_create", e).to_dict()}
