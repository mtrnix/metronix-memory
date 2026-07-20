"""Regression checks for the public hosted MCP authentication contract."""

from pathlib import Path

import pytest

DOCS = (
    Path("docs/MCP_API.md"),
    Path("docs/integrations/mcp-reference.md"),
)


def _normalized(content: str) -> str:
    """Make line wrapping in Markdown irrelevant to contract assertions."""
    return " ".join(content.split())


@pytest.mark.parametrize("path", DOCS)
def test_hosted_mcp_docs_describe_jwt_authentication(path: Path) -> None:
    content = _normalized(path.read_text())

    assert "Authorization: Bearer <jwt>" in content
    assert "AUTH_ENABLED=true" in content
    assert "401" in content


@pytest.mark.parametrize("path", DOCS)
def test_hosted_mcp_docs_describe_grants_and_deployment_key_limits(path: Path) -> None:
    content = _normalized(path.read_text())

    assert "ungranted workspace returns 403 before data access" in content
    assert "METRONIX_MCP_API_KEY" in content
    assert "development/bootstrap-only" in content
    assert "not accepted as a hosted-user credential" in content
    assert "does not grant workspace membership or delegation authority" in content


@pytest.mark.parametrize("path", DOCS)
def test_hosted_mcp_docs_do_not_present_deployment_key_as_bearer_credential(path: Path) -> None:
    content = _normalized(path.read_text())

    assert "Authorization: Bearer <METRONIX_MCP_API_KEY>" not in content
    assert "Authorization: Bearer <your-api-key>" not in content
