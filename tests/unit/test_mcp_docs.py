"""Regression checks for the public hosted MCP authentication contract."""

from pathlib import Path

import pytest

DOCS = (
    Path("docs/MCP_API.md"),
    Path("docs/integrations/mcp-reference.md"),
)

PUBLIC_MCP_MODE_DOCS = (
    Path("README.md"),
    Path(".env.example"),
    Path("docs/API.md"),
    Path("connecting_to_agent.md"),
    Path("install.md"),
    Path("prompts.md"),
    Path("docs/examples/python-sdk.md"),
    Path("docs/guides/agents-and-workspaces.md"),
    Path("docs/integrations/atomic-chat.md"),
    Path("docs/integrations/claude-code.md"),
    Path("docs/integrations/claude-code/prompt-1-install.md"),
    Path("docs/integrations/claude-desktop.md"),
    Path("docs/integrations/codex.md"),
    Path("docs/integrations/codex/prompt-1-install.md"),
    Path("docs/integrations/cursor.md"),
    Path("docs/integrations/hermes-agent.md"),
    Path("docs/integrations/hermes.md"),
    Path("docs/integrations/hermes/prompt-1-install.md"),
    Path("docs/integrations/langchain.md"),
    Path("docs/integrations/n8n.md"),
    Path("docs/integrations/nanobot.md"),
    Path("docs/integrations/nanoclaw.md"),
    Path("docs/integrations/openclaw.md"),
    Path("docs/integrations/opencode.md"),
    Path("docs/integrations/pi.md"),
    Path("docs/integrations/sdk-go.md"),
    Path("docs/integrations/sdk-python.md"),
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


@pytest.mark.parametrize("path", PUBLIC_MCP_MODE_DOCS)
def test_public_mcp_guidance_distinguishes_both_authentication_modes(path: Path) -> None:
    content = _normalized(path.read_text())

    assert "AUTH_ENABLED=false" in content
    assert "AUTH_ENABLED=true" in content
    assert "JWT" in content


def test_api_reference_mcp_auth_row_describes_mode_specific_bearer_credentials() -> None:
    content = _normalized(Path("docs/API.md").read_text())

    assert "JWT when `AUTH_ENABLED=true`" in content
    assert "`METRONIX_MCP_API_KEY` when `AUTH_ENABLED=false`" in content


def test_env_example_documents_legacy_key_is_ignored_in_jwt_mode() -> None:
    content = _normalized(Path(".env.example").read_text())

    assert "ignored when AUTH_ENABLED=true" in content
