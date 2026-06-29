"""Unit tests for the shared agent-id validation rule (metronix.core.utils)."""

from __future__ import annotations

import pytest

from metronix.core.utils import AGENT_ID_MAX_LENGTH, is_valid_agent_id


@pytest.mark.parametrize(
    "value",
    [
        "hermes",
        "my-agent-001",
        "3f2a9c4e5b6d7081a2b3c4d5e6f70811",  # uuid4().hex
        "12345678-1234-5678-1234-567812345678",  # dashed uuid
        "Agent_42",
        "a.b_c-d",
        "a",
        "a" * AGENT_ID_MAX_LENGTH,
    ],
)
def test_valid_ids(value: str) -> None:
    assert is_valid_agent_id(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",  # empty
        None,  # missing
        "a" * (AGENT_ID_MAX_LENGTH + 1),  # too long
        "a/b",  # path separator — breaks /agents/{id}
        "ag id",  # space
        "ag\tx",  # control char
        "agent#1",  # url-reserved
        "agent?x",
        "ляляля",  # non-ascii
        "agent\n",  # trailing newline — must not slip past $ (use \Z)
        "\nagent",  # leading newline
        "agent\nx",  # embedded newline
        "agent\r",  # trailing carriage return
    ],
)
def test_invalid_ids(value: str | None) -> None:
    assert is_valid_agent_id(value) is False
