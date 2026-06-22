from __future__ import annotations

import questionary
import questionary.constants

from .wizard import Prompter

# Softer indicator — a bullet point instead of a heavy filled circle.
questionary.constants.INDICATOR_SELECTED = "•"
questionary.constants.INDICATOR_UNSELECTED = "○"

# Plain-text instruction for the custom-profile checkbox.
# ANSI escapes are NOT supported here — questionary passes instruction
# as prompt_toolkit FormattedText, which ignores terminal escape codes.
# FormattedText lists (style, text) work on some Python versions but
# cause nested-tuple TypeError on Python 3.13+.
_CHECKBOX_INSTRUCTION = "(<space> select, <enter> confirm, <a> toggle all, <i> invert)"


def _safe_ask(question) -> str | None:
    """Call ``question.ask()`` safely, returning ``None`` on cancellation."""
    try:
        return question.ask()
    except KeyboardInterrupt:
        # questionary prints "Cancelled by user." already; treat as empty.
        return None


def _required_ask(question):
    """Call ``question.ask()``; raise KeyboardInterrupt on cancellation.

    Used for prompts where "cancel" means "abort the entire wizard"
    (select, confirm, checkbox).  The KeyboardInterrupt bubbles up to
    ``main()``'s handler which prints "Cancelled." and exits cleanly.
    """
    result = question.ask()
    if result is None:
        raise KeyboardInterrupt()
    return result


class QuestionaryPrompter(Prompter):
    def select(self, message: str, choices: list[str], default: str | None = None) -> str:
        return _required_ask(
            questionary.select(message, choices=choices, default=default)
        )

    def text(self, message: str, default: str = "") -> str:
        return _safe_ask(questionary.text(message, default=default)) or default

    def password(self, message: str) -> str:
        return _safe_ask(questionary.password(message)) or ""

    def confirm(self, message: str, default: bool = False) -> bool:
        return _required_ask(questionary.confirm(message, default=default))

    def checkbox(self, message: str, choices: list[str]) -> list[str]:
        result = _required_ask(
            questionary.checkbox(
                message,
                choices=choices,
                instruction=_CHECKBOX_INSTRUCTION,
            )
        ) or []

        # If the user pressed Enter without explicitly toggling anything (all
        # unchecked), ask for confirmation so an accidental Enter doesn't
        # silently skip the entire custom-profile selection.
        if not result and not questionary.confirm(
            "No services selected. Are you sure you want to continue with none?",
            default=False,
        ).ask():
            # Re-prompt — give the user another chance.
            return self.checkbox(message, choices)

        return result
