"""MCP tool: metatron_source_schemas — connector config schemas."""

from __future__ import annotations

from typing import Any

from metatron.mcp.errors import handle_tool_error
from metatron.mcp.server import mcp


@mcp.tool(
    description=(
        "List the config schema for each data-source connector type.\n\n"
        "Use this before metatron_source_create to learn which config fields a "
        "connector needs.\n\n"
        "**Returns:** schemas[] — each with type, label, category, and fields[] "
        "(name, label, type, required). Only data-source connectors are listed.\n\n"
        "**Working connectors:** confluence, jira, notion. The connectors github, "
        "gdrive, slack_history are registered but NOT implemented — creating them "
        "succeeds but sync will fail."
    ),
)
async def metatron_source_schemas(category: str | None = None) -> dict[str, Any]:
    """Return connector config schemas (connectors only)."""
    try:
        from metatron.connectors.schemas import CONNECTOR_SCHEMAS
        from metatron.mcp.tools.models import (
            SourceSchemaDTO,
            SourceSchemaField,
            SourceSchemasResponse,
        )

        out: list[SourceSchemaDTO] = []
        for schema in CONNECTOR_SCHEMAS.values():
            if schema.category != "connector":
                continue
            out.append(
                SourceSchemaDTO(
                    type=schema.type,
                    label=schema.label,
                    category=schema.category,
                    fields=[
                        SourceSchemaField(
                            name=f.name,
                            label=f.label,
                            type=f.type,
                            required=f.required,
                            placeholder=f.placeholder,
                        )
                        for f in schema.fields
                    ],
                )
            )
        return SourceSchemasResponse(schemas=out).model_dump()
    except Exception as e:
        return {"error": handle_tool_error("metatron_source_schemas", e).to_dict()}
