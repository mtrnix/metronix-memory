from metronix.connectors.schemas import (
    get_schema,
    validate_config,
    validate_config_for_update,
)


def test_gdrive_schema_fields():
    schema = get_schema("gdrive")
    assert schema is not None
    names = {f.name for f in schema.fields}
    assert names == {"credentials_json", "folder_id", "shared_drive_id"}
    assert schema.required_fields == ["credentials_json"]
    assert set(schema.secret_fields) == {"credentials_json"}


def test_gdrive_validate_service_account_ok():
    assert validate_config("gdrive", {"credentials_json": '{"x": 1}'}) == []


def test_gdrive_validate_missing_credentials_fails():
    errs = validate_config("gdrive", {"folder_id": "f"})
    assert len(errs) == 1
    assert "Service Account JSON is required" in errs[0]


def test_gdrive_validate_update_accepts_masked_secret():
    # A masked secret in update flow counts as present (unchanged).
    assert validate_config_for_update("gdrive", {"credentials_json": "***abcd"}) == []
