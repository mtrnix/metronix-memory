from __future__ import annotations

import questionary
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from questionary.constants import DEFAULT_QUESTION_PREFIX, DEFAULT_SELECTED_POINTER
from questionary.prompts.common import Choice, InquirerControl, Separator, create_inquirer_layout
from questionary.question import Question
from questionary.styles import merge_styles_default

from .wizard import Prompter


def _checkbox_enter_toggle(
    message: str, choices: list[str], pointer: str | None = None
) -> Question:
    """A multi-select checkbox where **Enter** also toggles (like Space).

    Standard questionary.checkbox uses Enter to submit. This version binds
    Enter to toggle the currently highlighted item, and Ctrl+D / Escape to
    submit the selection.
    """
    ic = InquirerControl(
        [Choice(c) for c in choices],
        default=None,
        pointer=pointer if pointer is not None else DEFAULT_SELECTED_POINTER,
    )

    def _tokens():
        tokens: list = [
            ("class:qmark", DEFAULT_QUESTION_PREFIX),
            ("class:question", f" {message} "),
        ]
        if ic.is_answered:
            n = len(ic.selected_options)
            if n == 0:
                tokens.append(("class:answer", "done"))
            else:
                tokens.append(("class:answer", f"done ({n} selections)"))
        else:
            tokens.append((
                "class:instruction",
                "(<space>/<enter> toggle, <ctrl+d> confirm, <a> toggle all, <i> invert)",
            ))
        return tokens

    def _values() -> list[str]:
        return [str(c.value) for c in ic.get_selected_values() if c.value is not None]

    layout = create_inquirer_layout(ic, _tokens)

    kb = KeyBindings()

    @kb.add(Keys.ControlC, eager=True)
    @kb.add(Keys.ControlQ, eager=True)
    def _abort(event):
        event.app.exit(exception=KeyboardInterrupt)

    @kb.add(" ", eager=True)
    @kb.add(Keys.ControlM, eager=True)  # ControlM = Enter / Return
    def _toggle(_event):
        val = ic.get_pointed_at().value
        if val in ic.selected_options:
            ic.selected_options.remove(val)
        else:
            ic.selected_options.append(val)

    @kb.add("i", eager=True)
    def _invert(_event):
        ic.selected_options = [
            c.value
            for c in ic.choices
            if not isinstance(c, Separator) and c.value not in ic.selected_options and not c.disabled
        ]

    @kb.add("a", eager=True)
    def _toggle_all(_event):
        all_selected = all(
            isinstance(c, Separator) or c.value in ic.selected_options or c.disabled
            for c in ic.choices
        )
        if all_selected:
            ic.selected_options = []
        else:
            ic.selected_options = [
                c.value
                for c in ic.choices
                if not isinstance(c, Separator) and not c.disabled
            ]

    @kb.add(Keys.Down, eager=True)
    @kb.add("j", eager=True)
    def _down(_event):
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    @kb.add(Keys.Up, eager=True)
    @kb.add("k", eager=True)
    def _up(_event):
        ic.select_previous()
        while not ic.is_selection_valid():
            ic.select_previous()

    @kb.add(Keys.ControlN, eager=True)
    def _emacs_down(_event):
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    @kb.add(Keys.ControlP, eager=True)
    def _emacs_up(_event):
        ic.select_previous()
        while not ic.is_selection_valid():
            ic.select_previous()

    @kb.add(Keys.ControlD, eager=True)
    @kb.add(Keys.Escape, eager=True)
    def _accept(event):
        ic.is_answered = True
        event.app.exit(result=_values())

    @kb.add(Keys.Any)
    def _ignore(_event):
        """Disallow inserting arbitrary characters."""

    return Question(
        Application(
            layout=layout,
            key_bindings=kb,
            style=merge_styles_default([]),
        )
    )


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
        return _checkbox_enter_toggle(message, choices).ask() or []
