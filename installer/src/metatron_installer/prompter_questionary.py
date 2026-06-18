from __future__ import annotations

import questionary
import questionary.constants

from .wizard import Prompter


# Softer indicator — a bullet point instead of a heavy filled circle.
questionary.constants.INDICATOR_SELECTED = "•"
questionary.constants.INDICATOR_UNSELECTED = "○"


class QuestionaryPrompter(Prompter):
    def select(self, message: str, choices: list[str], default: str | None = None) -> str:
        return questionary.select(message, choices=choices, default=default).ask()

    def text(self, message: str, default: str = "") -> str:
        return questionary.text(message, default=default).ask() or default

    def password(self, message: str) -> str:
        return questionary.password(message).ask() or ""

    def confirm(self, message: str, default: bool = False) -> bool:
        return questionary.confirm(message, default=default).ask()

    def checkbox(self, message: str, choices: list[str]) -> list[str]:
        # Highlight key hints in orange so they stand out.
        instruction = [
            ("", "("),
            ("fg:#ff8700 bold", "<space>"),
            ("", " select, "),
            ("fg:#ff8700 bold", "<enter>"),
            ("", " confirm, "),
            ("fg:#ff8700 bold", "<a>"),
            ("", " toggle all, "),
            ("fg:#ff8700 bold", "<i>"),
            ("", " invert)"),
        ]
        result = questionary.checkbox(
            message,
            choices=choices,
            instruction=instruction,  # type: ignore[arg-type]  # FormattedText accepted at runtime
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
