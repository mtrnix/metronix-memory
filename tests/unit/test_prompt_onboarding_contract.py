"""Regression checks for the Codex/Hermes Prompt 1 -> Prompt 2 onboarding contract (#434).

Scope is intentionally the same 4 files #433 touched — no numbered prompt-3/
prompt-4 file and no non-numbered codex.md/hermes.md/hermes-agent.md here;
extending coverage to those is tracked separately in #449. Never runs a real
Codex or Hermes installation — these are plain text/ordering assertions
against the prompt markdown itself.
"""

from pathlib import Path

import pytest

PROMPT_1_DOCS = (
    Path("docs/integrations/codex/prompt-1-install.md"),
    Path("docs/integrations/hermes/prompt-1-install.md"),
)

PROMPT_2_DOCS = (
    Path("docs/integrations/codex/prompt-2-memory.md"),
    Path("docs/integrations/hermes/prompt-2-memory.md"),
)


def _normalized(content: str) -> str:
    """Make line wrapping in Markdown irrelevant to contract assertions."""
    return " ".join(content.split())


@pytest.mark.parametrize("path", PROMPT_1_DOCS)
def test_prompt_1_does_not_present_shared_key_as_sufficient_for_memory(path: Path) -> None:
    content = _normalized(path.read_text())

    assert "authenticates the MCP transport only" in content
    assert "AUTH_REQUIRED" in content
    assert "personal API key" in content
    assert "mtk_" in content


@pytest.mark.parametrize("path", PROMPT_1_DOCS)
def test_prompt_1_credential_note_never_prints_a_password(path: Path) -> None:
    content = path.read_text()

    # The seed flow is referenced (AUTH_PASSWORD as a name), never reproduced
    # with an actual value — no "AUTH_PASSWORD=<something>" assignment here.
    assert "AUTH_PASSWORD=" not in content


@pytest.mark.parametrize("path", PROMPT_2_DOCS)
def test_prompt_2_preflight_precedes_the_policy_file_write(path: Path) -> None:
    """The old bug: write (AGENTS.md/SOUL.md) happened before verify.

    Fails if the file text ever regresses to writing the policy block before
    (or without) the metronix_memory_list preflight check.
    """
    content = _normalized(path.read_text())

    preflight_marker = "Call `metronix_memory_list("
    write_marker_candidates = [
        "Write the routing rule (AGENTS.md)",
        "Upgrade the routing rule to mandatory (SOUL.md)",
    ]
    write_markers_present = [m for m in write_marker_candidates if m in content]

    assert preflight_marker in content, f"{path}: no metronix_memory_list preflight call found"
    assert write_markers_present, f"{path}: no policy-file write step found"

    preflight_index = content.index(preflight_marker)
    write_index = min(content.index(m) for m in write_markers_present)
    assert preflight_index < write_index, (
        f"{path}: the policy-file write step appears before the preflight check"
    )


@pytest.mark.parametrize("path", PROMPT_2_DOCS)
def test_prompt_2_empty_memory_list_is_not_treated_as_denial(path: Path) -> None:
    """First fork resolved explicitly in the doc text (see #433's PR description):
    success is the absence of AUTH_REQUIRED, not a non-empty records list.
    """
    content = _normalized(path.read_text())

    assert "AUTH_REQUIRED" in content
    assert "empty" in content and "not a failure" in content
    assert "do not treat" in content.lower() or "not treat" in content.lower()


@pytest.mark.parametrize("path", PROMPT_2_DOCS)
def test_prompt_2_denial_path_stops_before_editing_the_policy_file(path: Path) -> None:
    content = _normalized(path.read_text())

    assert "STOP" in content
    assert "Do NOT edit" in content
    assert "recovery path" in content or "recover" in content


@pytest.mark.parametrize("path", PROMPT_2_DOCS)
def test_prompt_2_treats_every_error_as_denial_not_just_auth_required(path: Path) -> None:
    """#450's review: the old criterion ("no error field, or error.code is
    anything other than AUTH_REQUIRED") reads any non-AUTH_REQUIRED error as
    success. test_memory_list_preflight_contract.py proves an authenticated,
    grant-less principal is denied with WORKSPACE_NOT_FOUND, not
    AUTH_REQUIRED — the doc text must name that failure explicitly, and stop
    on a bad/missing response generally, not only on the one code.
    """
    content = _normalized(path.read_text())

    assert "WORKSPACE_NOT_FOUND" in content
    assert "INVALID_PARAMS" in content
    assert "INTERNAL_ERROR" in content
    assert "non-2xx" in content
    assert "not being available as a tool" in content
    assert "do not special-case" in content.lower()
