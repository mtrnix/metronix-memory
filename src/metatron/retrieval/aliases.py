"""Person name aliases for Jira assignee matching.

Maps Russian nicknames, short forms, and transliterations to full Jira
display names so that queries like "Что делает Женя?" find tasks assigned
to "Evgeny Shcherbinin".

NOTE: This module is the hardcoded fallback. New deployments should rely
on AliasRegistry (alias_registry.py) which auto-populates from Jira sync.
Use seed_custom_aliases() to migrate these entries into the registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metatron.retrieval.alias_registry import AliasRegistry

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


def resolve_person_name(extracted: str) -> list[str]:
    """Resolve an extracted person name to Jira assignee display names.

    Args:
        extracted: Name extracted from query (e.g. "Женя", "Evgeny").

    Returns:
        List of possible full Jira display names. If no alias found,
        returns the original name capitalized as a single-element list
        so the caller can still attempt an exact-match search.
    """
    from metatron.retrieval.alias_registry import _strip_russian_case_ending

    key = extracted.strip().lower()
    if key in NAME_ALIASES:
        return NAME_ALIASES[key]
    # Try stem-stripped form for Russian case endings
    stem = _strip_russian_case_ending(key)
    if stem and stem in NAME_ALIASES:
        return NAME_ALIASES[stem]
    # No alias — return original capitalized as fallback
    return [extracted.strip().capitalize()]


def seed_custom_aliases(registry: AliasRegistry) -> int:
    """Seed hardcoded NAME_ALIASES into an AliasRegistry as custom aliases.

    Idempotent — safe to call multiple times. Only adds aliases that
    don't already exist in the registry.

    Returns:
        Number of aliases added.
    """
    added = 0
    for alias, names in NAME_ALIASES.items():
        if names:
            registry.add_custom_alias(alias, names[0])
            added += 1
    return added
