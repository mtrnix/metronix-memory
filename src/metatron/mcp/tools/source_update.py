"""MCP tool: metatron_source_update — update a data-source connection."""

from __future__ import annotations

from typing import Any

from metatron.mcp.errors import handle_tool_error
from metatron.mcp.server import mcp


@mcp.tool(
    description=(
        "Update a data source's name, enabled flag, and/or config.\n\n"
        "**Parameters:**\n"
        "- connection_id: the source to update (required)\n"
        "- workspace_id: target workspace (optional, defaults to 'default')\n"
        "- name / enabled / config: fields to change (omit to leave unchanged)\n\n"
        "When updating config, send the FULL config dict. To keep a secret "
        "unchanged, pass its masked value (the '***...' string from "
        "metatron_source_list) — it is preserved automatically.\n\n"
        "**Returns:** the updated source with masked secrets."
    ),
)
async def metatron_source_update(
    connection_id: str,
    workspace_id: str | None = None,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Update a data-source connection."""
    try:
        from metatron.connectors.schemas import validate_config_for_update
        from metatron.mcp.tools._source_deps import resolve
        from metatron.mcp.tools.models import SourceDTO

        ws_id, store, fernet_key = resolve(workspace_id)
        existing = await store.get_connection(connection_id, fernet_key)
        if existing is None or existing["workspace_id"] != ws_id:
            raise ValueError("Connection not found")

        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if enabled is not None:
            updates["enabled"] = enabled
        if config is not None:
            errors = validate_config_for_update(existing["connector_type"], config)
            if errors:
                raise ValueError("; ".join(errors))
            # No pre-merge here: store.update_connection merges masked secrets.
            updates["config"] = config

        if not updates:
            raise ValueError("No fields to update")

        result = await store.update_connection(connection_id, updates, fernet_key)
        if result is None:
            raise ValueError("Connection not found")
        return SourceDTO(**result).model_dump()
    except Exception as e:
        return {"error": handle_tool_error("metatron_source_update", e).to_dict()}
