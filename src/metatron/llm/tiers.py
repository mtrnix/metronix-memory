"""Map an LLM ``call_site`` to a model tier (MTRNIX-397, A).

Service calls (query resolution, expansion, classification, translation, NER, slot
extraction) run on a cheaper/faster FAST model; the final answer (``rag_answer``) runs
on the HEAVY model. Tiering is provider-agnostic at the routing level — only the model
*name* is DeepSeek-specific, so for any non-DeepSeek provider this is a no-op and the
provider's configured model is used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metatron.core.config import Settings

# Service call_sites that should use the FAST model. Everything else (notably
# ``rag_answer``) stays on the HEAVY model.
FAST_CALL_SITES: frozenset[str] = frozenset(
    {
        "resolve_query",
        "translate_query",
        "query_classifier",
        "query_expansion",
        "routing",
        "hyde",
        "ner_extraction",
        "slot_extraction",
        "translation_to_english",
        "translation_to_russian",
    }
)


def resolve_model_for_call_site(
    call_site: str, explicit_model: str | None, settings: Settings
) -> str | None:
    """Return the model-name override for ``call_site``, or ``None`` for the provider default.

    Rules:
    - an explicit ``model=`` override always wins;
    - tiering only applies to the ``deepseek`` provider (model names are deepseek-specific);
      any other provider returns ``None`` (use its configured model);
    - FAST call_sites resolve to ``deepseek_model_fast``, inheriting the heavy
      ``deepseek_model`` at runtime when the FAST var is empty (so an unset FAST var is
      byte-identical to today);
    - HEAVY call_sites return ``None`` so ``get_llm`` uses the provider default
      (``deepseek_model``).
    """
    if explicit_model:
        return explicit_model
    if getattr(settings, "llm_provider", "") != "deepseek":
        return None
    if call_site in FAST_CALL_SITES:
        return settings.deepseek_model_fast or settings.deepseek_model
    return None
