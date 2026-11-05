"""Issue #449 audit: prompt-3/prompt-4 must not reintroduce the #433
"write before verify" ordering bug.

Prompt 3 migrates durable knowledge into Metronix; prompt 4 rolls the
prompt-2 routing rule back to optional. Neither may install a mandatory
routing rule (the failure mode #433 fixed in prompt 2: a read-only grant
would then enforce a rule the client can't satisfy), and prompt 3 may
only retire originals after each item is *confirmed* stored. These
regression tests pin the audited state so future edits can't silently
reintroduce the ordering problem.
"""

from pathlib import Path

import pytest

PROMPT3_FILES = (
    Path("docs/integrations/codex/prompt-3-migrate.md"),
    Path("docs/integrations/hermes/prompt-3-migrate.md"),
    Path("docs/integrations/claude-code/prompt-3-migrate.md"),
)

PROMPT4_FILES = (
    Path("docs/integrations/codex/prompt-4-rollback.md"),
    Path("docs/integrations/hermes/prompt-4-rollback.md"),
    Path("docs/integrations/claude-code/prompt-4-rollback.md"),
)

_ROUTING_RULE_DELIM = "--- metronix-config ---"


def _normalized(text: str) -> str:
    """Collapse Markdown line wrapping so contract assertions ignore it."""
    return " ".join(text.split())


@pytest.mark.parametrize("path", PROMPT3_FILES, ids=lambda p: str(p))
def test_prompt3_installs_no_routing_rule(path: Path) -> None:
    """Prompt 3 migrates knowledge; it must not install a routing rule, so
    there is no mandatory-rule-without-write-access failure mode."""
    content = _normalized(path.read_text())
    assert _ROUTING_RULE_DELIM not in content


@pytest.mark.parametrize("path", PROMPT3_FILES, ids=lambda p: str(p))
def test_prompt3_retires_originals_only_after_confirmed_storage(path: Path) -> None:
    """Originals are retired only once the migrated item is confirmed
    stored — a failed store must never delete the source of truth."""
    content = _normalized(path.read_text())
    assert "confirmed stored" in content


@pytest.mark.parametrize("path", PROMPT4_FILES, ids=lambda p: str(p))
def test_prompt4_makes_no_memory_writes(path: Path) -> None:
    """Prompt 4 only downgrades the routing rule wording; it performs no
    memory writes, so no write-access preflight is required."""
    content = _normalized(path.read_text())
    assert "metronix_memory_store(" not in content
    assert "OPTIONAL" in content
