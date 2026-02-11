"""LLM-based query expansion for improved BM25 + semantic search recall."""
from __future__ import annotations

import structlog

from metatron.llm import chat_completion
from metatron.observability.metrics import timed

logger = structlog.get_logger()

QUERY_EXPANSION_PROMPT = """\
You are a search query optimizer for an enterprise knowledge base containing \
Confluence pages and Jira issues.

Your task: rewrite the user's question into an expanded search query that will \
help find the most relevant documents using both semantic search (dense vectors) \
and keyword search (BM25).

Rules:
1. Keep the original meaning intact
2. Add synonyms, related terms, and keywords likely to appear in relevant documents
3. For questions about current activity/status — add: "In Progress", "active", \
"assigned", "current", "working on", "sprint"
4. For questions about completed work — add: "Done", "completed", "finished", \
"resolved", "closed"
5. For questions about plans — add: "BACKLOG", "planned", "TODO", "upcoming", "next"
6. For person-specific questions — keep the person's name and add task-related terms
7. Add both English AND Russian keywords since documents may be in either language
8. Output ONLY the expanded query, nothing else. No explanations, no quotes, \
no prefixes.
9. Keep it under 200 words — this is a search query, not an essay.

Examples:
- "What is the team doing?" → team current tasks In Progress active работает \
sprint assigned текущие задачи в работе исполнитель
- "What happened last week?" → completed Done last week finished resolved \
закрыто завершено прошлая неделя результаты
- "Что делает Женя?" → Женя Евгений Evgeny assigned tasks In Progress working \
активные задачи исполнитель в работе
- "What is Metatron?" → Metatron MTRNIX platform architecture описание система \
knowledge base
- "Кто отвечает за инфраструктуру?" → infrastructure инфраструктура responsible \
assignee owner DevOps deployment ответственный"""


@timed("query_expansion")
def expand_query(query: str, timeout: int = 10) -> str:
    """Use LLM to expand user query with search-relevant keywords.

    Falls back to original query if LLM call fails or expansion is disabled.
    """
    from metatron.core.config import Settings

    if not Settings().query_expansion_enabled:
        return query

    try:
        expanded = chat_completion(
            messages=[
                {"role": "system", "content": QUERY_EXPANSION_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.1,
            max_tokens=300,
            timeout=timeout,
        )
        expanded = expanded.strip().strip('"').strip("'")

        if expanded and len(expanded) > len(query):
            logger.info(
                "query.expanded",
                original=query[:100],
                expanded=expanded[:200],
                expansion_ratio=round(len(expanded) / len(query), 1),
            )
            return expanded

        return query
    except Exception as e:
        logger.warning("query.expansion_failed", error=str(e))
        return query
