from metronix.connectors.schemas import CONNECTOR_SCHEMAS, get_schema, resolve_connector_type


def test_resolve_connector_type_maps_google_drive_to_gdrive():
    assert resolve_connector_type("google_drive") == "gdrive"


def test_resolve_connector_type_leaves_canonical_name_unchanged():
    assert resolve_connector_type("gdrive") == "gdrive"


def test_resolve_connector_type_passes_through_unknown_names():
    # Callers still validate the result against CONNECTOR_SCHEMAS themselves;
    # resolving must not mask an unknown/typo'd connector type as valid.
    assert resolve_connector_type("sap") == "sap"


def test_resolved_alias_is_a_registered_schema():
    resolved = resolve_connector_type("google_drive")
    assert resolved in CONNECTOR_SCHEMAS
    assert "google_drive" not in CONNECTOR_SCHEMAS


def test_get_schema_is_alias_aware():
    # Direct regression for the schema-lookup gap: get_schema() must resolve
    # the alias itself, not rely on the caller having already resolved it.
    assert get_schema("google_drive") is get_schema("gdrive")
    assert get_schema("google_drive") is not None
    assert get_schema("google_drive").type == "gdrive"


def test_get_schema_unknown_type_returns_none():
    assert get_schema("sap") is None
