"""Person name aliases for Jira assignee matching.

Maps Russian nicknames, short forms, and transliterations to full Jira
display names so that queries like "Что делает Женя?" find tasks assigned
to "Evgeny Shcherbinin".
"""
from __future__ import annotations

from typing import List

# Mapping: lowercase alias -> list of possible full Jira displayName values.
# Each alias can map to multiple names (rare but possible).
# Add new team members here as they join.
NAME_ALIASES: dict[str, list[str]] = {
    # Evgeny Shcherbinin
    "женя": ["Evgeny Shcherbinin"],
    "евгений": ["Evgeny Shcherbinin"],
    "щербинин": ["Evgeny Shcherbinin"],
    "evgeny": ["Evgeny Shcherbinin"],
    "shcherbinin": ["Evgeny Shcherbinin"],
    # Kuzmin Konstantin
    "константин": ["Kuzmin Konstantin"],
    "костя": ["Kuzmin Konstantin"],
    "konstantin": ["Kuzmin Konstantin"],
    "kuzmin": ["Kuzmin Konstantin"],
    # Seliverstov Sergej
    "сергей": ["Seliverstov Sergej"],
    "серёжа": ["Seliverstov Sergej"],
    "sergej": ["Seliverstov Sergej"],
    "sergey": ["Seliverstov Sergej"],
    "seliverstov": ["Seliverstov Sergej"],
    # Pozdnyakov Vadim
    "вадим": ["Pozdnyakov Vadim"],
    "vadim": ["Pozdnyakov Vadim"],
    "pozdnyakov": ["Pozdnyakov Vadim"],
    # Andrew Ermakov
    "андрей": ["Andrew Ermakov"],
    "andrew": ["Andrew Ermakov"],
    "ermakov": ["Andrew Ermakov"],
    # Artem Tov Ben
    "артём": ["Artem Tov Ben"],
    "артем": ["Artem Tov Ben"],
    "artem": ["Artem Tov Ben"],
    # Vasiliy Kazanin
    "василий": ["Vasiliy Kazanin"],
    "вася": ["Vasiliy Kazanin"],
    "vasiliy": ["Vasiliy Kazanin"],
    "kazanin": ["Vasiliy Kazanin"],
    # Vladimir Belykh
    "владимир": ["Vladimir Belykh"],
    "вова": ["Vladimir Belykh"],
    "vladimir": ["Vladimir Belykh"],
    "belykh": ["Vladimir Belykh"],
}


def resolve_person_name(extracted: str) -> List[str]:
    """Resolve an extracted person name to Jira assignee display names.

    Args:
        extracted: Name extracted from query (e.g. "Женя", "Evgeny").

    Returns:
        List of possible full Jira display names. If no alias found,
        returns the original name capitalized as a single-element list
        so the caller can still attempt an exact-match search.
    """
    key = extracted.strip().lower()
    if key in NAME_ALIASES:
        return NAME_ALIASES[key]
    # No alias — return original capitalized as fallback
    return [extracted.strip().capitalize()]
