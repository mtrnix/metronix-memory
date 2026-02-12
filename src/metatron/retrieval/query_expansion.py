"""LLM-based query expansion for improved BM25 + semantic search recall."""
from __future__ import annotations

import structlog

from metatron.llm import chat_completion
from metatron.observability.metrics import timed

logger = structlog.get_logger()

_EXPANSION_PROMPT_TEMPLATE = """\
You are a search query optimizer for an enterprise knowledge base containing \
Confluence pages and Jira issues.

Your task: rewrite the user's question into an expanded search query that will \
help find the most relevant documents using both semantic search (dense vectors) \
and keyword search (BM25).

IMPORTANT: Expand ONLY in {language}. Do NOT add keywords in other languages.

Rules:
1. Keep the original query terms as the MOST IMPORTANT part — always include them first
2. Add at most 5-7 additional keywords that are specific to the topic
3. Do NOT add generic terms like "architecture", "components", "overview", \
"description", "система", "описание" — only add terms specific to the topic
4. For questions about current activity/status — add status keywords \
("In Progress", "active", "sprint" for English; "В работе", "активные", "спринт" \
for Russian)
5. For questions about completed work — add completion keywords \
("Done", "resolved", "closed" for English; "Закрыто", "завершено" for Russian)
6. For questions about plans — add planning keywords \
("BACKLOG", "planned", "TODO" for English; "Бэклог", "запланировано" for Russian)
7. For person-specific questions — keep the person's name and add task-related terms
8. Output ONLY the expanded query, nothing else. No explanations, no quotes, \
no prefixes.
9. Keep the expansion SHORT — the expanded query should be at most 2-3x the \
length of the original.

{examples}"""

_EXAMPLES_EN = """\
Examples:
- "What is the team doing?" → team doing current tasks In Progress active sprint
- "What happened last week?" → happened last week completed Done resolved
- "What is Metatron?" → Metatron MTRNIX platform knowledge base"""

_EXAMPLES_RU = """\
Examples:
- "Что делает команда?" → команда делает текущие задачи В работе активные спринт
- "Что было на прошлой неделе?" → прошлая неделя завершено закрыто результаты
- "Что делает Женя?" → Женя Евгений задачи исполнитель в работе"""


def _build_expansion_prompt(query: str) -> str:
    """Build a language-specific expansion prompt based on the query language."""
    from metatron.retrieval.search import detect_response_language

    lang = detect_response_language(query)
    if lang == "Russian":
        return _EXPANSION_PROMPT_TEMPLATE.format(language="Russian", examples=_EXAMPLES_RU)
    return _EXPANSION_PROMPT_TEMPLATE.format(language="English", examples=_EXAMPLES_EN)


@timed("query_expansion")
def expand_query(query: str, timeout: int = 10) -> str:
    """Use LLM to expand user query with search-relevant keywords.

    Expands only in the query's language (EN or RU). The translation step
    in the search pipeline handles cross-language matching separately.

    Falls back to original query if LLM call fails or expansion is disabled.
    """
    from metatron.core.config import Settings

    if not Settings().query_expansion_enabled:
        return query

    try:
        prompt = _build_expansion_prompt(query)
        expanded = chat_completion(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
            temperature=0.1,
            max_tokens=300,
            timeout=timeout,
        )
        expanded = expanded.strip().strip('"').strip("'")

        if not expanded or len(expanded) <= len(query):
            return query

        ratio = len(expanded) / len(query)

        # Too aggressive — discard entirely
        if ratio > 4.0:
            logger.warning(
                "query.expansion_too_aggressive",
                original=query[:100],
                expansion_ratio=round(ratio, 1),
            )
            return query

        # Over 3x — truncate to fit within 3x budget
        max_len = len(query) * 3
        if len(expanded) > max_len:
            words = expanded.split()
            truncated: list[str] = []
            length = 0
            for w in words:
                if length + len(w) + 1 > max_len:
                    break
                truncated.append(w)
                length += len(w) + 1
            expanded = " ".join(truncated)

        logger.info(
            "query.expanded",
            original=query[:100],
            expanded=expanded[:200],
            expansion_ratio=round(len(expanded) / len(query), 1),
        )
        return expanded
    except Exception as e:
        logger.warning("query.expansion_failed", error=str(e))
        return query
