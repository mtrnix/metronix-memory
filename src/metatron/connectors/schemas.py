"""Configuration schemas for connector types.

Defines required/optional fields per connector type for validation,
UI form generation, and secret masking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SECRET_MASK = "***"


@dataclass(frozen=True)
class ConfigField:
    """A single configuration field for a connector type."""

    name: str
    label: str
    type: str  # "string", "url", "secret", "number", "boolean"
    required: bool = True
    placeholder: str = ""


@dataclass(frozen=True)
class ConnectorSchema:
    """Schema definition for a connector type."""

    type: str
    label: str
    category: str  # "connector" or "channel"
    fields: list[ConfigField] = field(default_factory=list)

    @property
    def required_fields(self) -> list[str]:
        return [f.name for f in self.fields if f.required]

    @property
    def secret_fields(self) -> list[str]:
        return [f.name for f in self.fields if f.type == "secret"]


_F = ConfigField

CONNECTOR_SCHEMAS: dict[str, ConnectorSchema] = {
    "confluence": ConnectorSchema(
        type="confluence",
        label="Confluence",
        category="connector",
        fields=[
            _F(
                name="url", label="Confluence URL",
                type="url", placeholder="https://your-domain.atlassian.net",
            ),
            _F(name="username", label="Username/Email", type="string"),
            _F(name="api_token", label="API Token", type="secret"),
            _F(
                name="space_key", label="Space Key",
                type="string", required=False,
                placeholder="Optional — sync all spaces",
            ),
        ],
    ),
    "jira": ConnectorSchema(
        type="jira",
        label="Jira",
        category="connector",
        fields=[
            _F(name="url", label="Jira URL", type="url"),
            _F(name="username", label="Username/Email", type="string"),
            _F(name="api_token", label="API Token", type="secret"),
            _F(
                name="project_key", label="Project Key",
                type="string", required=False,
            ),
        ],
    ),
    "notion": ConnectorSchema(
        type="notion",
        label="Notion",
        category="connector",
        fields=[
            _F(name="api_token", label="Integration Token", type="secret"),
        ],
    ),
    "github": ConnectorSchema(
        type="github",
        label="GitHub",
        category="connector",
        fields=[
            _F(
                name="token", label="Personal Access Token",
                type="secret",
            ),
            _F(name="org", label="Organization", type="string", required=False),
            _F(
                name="repos", label="Repositories",
                type="string", required=False,
                placeholder="repo1,repo2 or * for all",
            ),
        ],
    ),
    "gdrive": ConnectorSchema(
        type="gdrive",
        label="Google Drive",
        category="connector",
        fields=[
            _F(
                name="credentials_json",
                label="Service Account JSON", type="secret",
            ),
            _F(
                name="folder_id", label="Folder ID",
                type="string", required=False,
            ),
            _F(
                name="shared_drive_id", label="Shared Drive ID",
                type="string", required=False,
            ),
        ],
    ),
    "slack_history": ConnectorSchema(
        type="slack_history",
        label="Slack History",
        category="connector",
        fields=[
            _F(
                name="bot_token", label="Bot Token (xoxb-...)",
                type="secret",
            ),
            _F(
                name="channels", label="Channels",
                type="string", required=False,
                placeholder="channel1,channel2 or * for all",
            ),
        ],
    ),
    "telegram": ConnectorSchema(
        type="telegram",
        label="Telegram Bot",
        category="channel",
        fields=[
            _F(
                name="bot_token", label="Bot Token",
                type="secret", placeholder="123456:ABC-DEF...",
            ),
        ],
    ),
    "discord": ConnectorSchema(
        type="discord",
        label="Discord Bot",
        category="channel",
        fields=[
            _F(name="bot_token", label="Bot Token", type="secret"),
        ],
    ),
    "slack": ConnectorSchema(
        type="slack",
        label="Slack Bot",
        category="channel",
        fields=[
            _F(
                name="bot_token", label="Bot Token (xoxb-...)",
                type="secret",
            ),
            _F(
                name="app_token", label="App Token (xapp-...)",
                type="secret",
            ),
            _F(
                name="signing_secret", label="Signing Secret",
                type="secret", required=False,
            ),
        ],
    ),
}


def get_schema(connector_type: str) -> ConnectorSchema | None:
    """Get the schema for a connector type, or None if unknown."""
    return CONNECTOR_SCHEMAS.get(connector_type)


def validate_config(connector_type: str, config: dict) -> list[str]:
    """Validate config against the schema for a connector type.

    Returns a list of error messages (empty = valid).
    """
    schema = CONNECTOR_SCHEMAS.get(connector_type)
    if schema is None:
        return [f"Unknown connector type: {connector_type}"]

    errors: list[str] = []
    for field_name in schema.required_fields:
        value = config.get(field_name)
        if not value or (isinstance(value, str) and not value.strip()):
            label = next(
                f.label for f in schema.fields if f.name == field_name
            )
            errors.append(f"{label} is required")
    return errors


def mask_secrets(connector_type: str, config: dict) -> dict:
    """Return a copy of config with secret fields replaced by '***'."""
    schema = CONNECTOR_SCHEMAS.get(connector_type)
    if schema is None:
        return config

    masked = dict(config)
    for field_name in schema.secret_fields:
        if field_name in masked and masked[field_name]:
            masked[field_name] = SECRET_MASK
    return masked


def merge_config(
    connector_type: str, old_config: dict, new_config: dict,
) -> dict:
    """Merge new_config into old_config, preserving masked secrets.

    If a secret field in new_config equals SECRET_MASK, keep old value.
    """
    schema = CONNECTOR_SCHEMAS.get(connector_type)
    if schema is None:
        return new_config

    merged = dict(new_config)
    secret_fields = set(schema.secret_fields)
    for field_name in secret_fields:
        if merged.get(field_name) == SECRET_MASK and field_name in old_config:
            merged[field_name] = old_config[field_name]
    return merged
