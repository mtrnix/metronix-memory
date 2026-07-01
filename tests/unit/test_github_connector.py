from metronix.connectors.schemas import get_schema


def test_github_schema_has_base_url_optional():
    schema = get_schema("github")
    assert schema is not None
    field_names = [f.name for f in schema.fields]
    assert "base_url" in field_names
    base_url = next(f for f in schema.fields if f.name == "base_url")
    assert base_url.required is False
    assert base_url.type == "url"


def test_github_schema_token_required_secret():
    schema = get_schema("github")
    token = next(f for f in schema.fields if f.name == "token")
    assert token.required is True
    assert token.type == "secret"
    assert "token" in schema.secret_fields
