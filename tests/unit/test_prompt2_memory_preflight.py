"""The Prompt 2 memory preflight must prove BOTH read and write access before
the mandatory routing rule is installed.

A read-only grant passes ``metronix_memory_list`` but then fails the first
``metronix_memory_store`` the installed rule mandates, leaving the client
enforcing a rule it can't satisfy (toomij99, PR #450 / #433). The write check
has to be non-mutating: ``metronix_memory_delete`` against a synthetic id that
cannot exist clears the same write-authorization gate as
``metronix_memory_store`` and then stops at ``DOCUMENT_NOT_FOUND``.
"""

from pathlib import Path

import pytest

PROMPT2_FILES = (
    Path("docs/integrations/codex/prompt-2-memory.md"),
    Path("docs/integrations/hermes/prompt-2-memory.md"),
    Path("docs/integrations/claude-code/prompt-2-memory.md"),
    Path("prompts.md"),
)

_ROUTING_RULE_DELIM = "--- metronix-config ---"


def _normalized(text: str) -> str:
    """Collapse Markdown line wrapping so contract assertions ignore it."""
    return " ".join(text.split())


def _prompt2_section(path: Path) -> str:
    """The Prompt 2 body, normalized — the whole file, except prompts.md
    bundles all four prompts so it is sliced to the Prompt 2 section first."""
    raw = path.read_text()
    if path.name == "prompts.md":
        start = raw.index("## Prompt 2")
        raw = raw[start : raw.index("## Prompt 3", start)]
    return _normalized(raw)


@pytest.mark.parametrize("path", PROMPT2_FILES, ids=lambda p: str(p))
def test_preflight_has_a_read_check_and_a_nonmutating_write_probe(path: Path) -> None:
    section = _prompt2_section(path)

    assert "metronix_memory_list(" in section, "read check missing"
    assert "metronix_memory_delete(" in section, "write-capability probe missing"
    assert "metronix-preflight-probe-" in section, "synthetic probe id missing"
    assert "deletes nothing" in section, "probe not described as non-mutating"
    assert "DOCUMENT_NOT_FOUND" in section, "write-probe pass signal missing"


@pytest.mark.parametrize("path", PROMPT2_FILES, ids=lambda p: str(p))
def test_write_probe_runs_before_the_routing_rule_is_written(path: Path) -> None:
    section = _prompt2_section(path)

    assert section.index("metronix_memory_delete(") < section.index(_ROUTING_RULE_DELIM), (
        "the write probe must be ordered before the metronix-config block the prompt installs"
    )


@pytest.mark.parametrize("path", PROMPT2_FILES, ids=lambda p: str(p))
def test_preflight_stays_fail_closed_and_keeps_the_auth_recovery_path(path: Path) -> None:
    section = _prompt2_section(path)

    # AUTH_REQUIRED keeps its dedicated recovery path...
    assert "AUTH_REQUIRED" in section
    assert "self-provision" in section
    # ...but it is explicitly not the only failure that stops the file edit.
    assert "not special-case" in section
