from __future__ import annotations

import questionary
import questionary.constants

from .wizard import Prompter

# Softer indicator — a bullet point instead of a heavy filled circle.
questionary.constants.INDICATOR_SELECTED = "•"
questionary.constants.INDICATOR_UNSELECTED = "○"

# Orange ANSI escape for key hints in the checkbox instruction.
# Uses 256-colour code 208 (orange) — avoids FormattedText nesting issues
# that cause TypeError on Python 3.13 / newer prompt_toolkit versions.
_ORANGE = "\033[38;5;208m"
_RESET = "\033[0m"
_CHECKBOX_INSTRUCTION = (
    f"({_ORANGE}<space>{_RESET} select, "
    f"{_ORANGE}<enter>{_RESET} confirm, "
    f"{_ORANGE}<a>{_RESET} toggle all, "
    f"{_ORANGE}<i>{_RESET} invert)"
)


def _safe_ask(question) -> str | None:
    """Call ``question.ask()`` safely, returning ``None`` on cancellation."""
    try:
        return question.ask()
    except KeyboardInterrupt:
        # questionary prints "Cancelled by user." already; treat as empty.
        return None


class QuestionaryPrompter(Prompter):
    def select(self, message: str, choices: list[str], default: str | None = None) -> str:
        return questionary.select(message, choices=choices, default=default).ask()

    def text(self, message: str, default: str = "") -> str:
        return _safe_ask(questionary.text(message, default=default)) or default

    def password(self, message: str) -> str:
        return _safe_ask(questionary.password(message)) or ""

    def confirm(self, message: str, default: bool = False) -> bool:
        return questionary.confirm(message, default=default).ask()

    def checkbox(self, message: str, choices: list[str]) -> list[str]:
        # Plain-string instruction with ANSI orange escapes — avoids
        # FormattedText nesting TypeError on Python 3.13 / newer
        # prompt_toolkit versions.
        result = questionary.checkbox(
            message,
            choices=choices,
            instruction=_CHECKBOX_INSTRUCTION,
        ).ask() or []

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
