"""Skill engine — load, select, and build prompts from skills.

Skills are Markdown documents stored in PostgreSQL. The engine
matches user queries to relevant skills (by triggers and tags),
then formats them into the LLM prompt so the router knows what
tools are available.
"""

from __future__ import annotations

import structlog

from metronix.core.models import Skill
from metronix.storage.postgres import PostgresStore

logger = structlog.get_logger()


class SkillEngine:
    """Manages skill loading, matching, and prompt construction.

    Skills are loaded from PostgreSQL. Builtin skills are seeded
    from .md files in skills/builtin/ on first migration.
    """

    def __init__(self, store: PostgresStore) -> None:
        self._store = store

    async def load_skills(self, workspace_id: str) -> list[Skill]:
        """Load all enabled skills for a workspace (including globals).

        Args:
            workspace_id: Current workspace context.

        Returns:
            List of enabled Skill objects.
        """
        logger.info("skills.engine.load", workspace_id=workspace_id)
        # TODO: implement skill loading
        # return await self._store.list_skills(workspace_id=workspace_id, enabled_only=True)
        raise NotImplementedError("Skill loading not yet implemented")

    async def select_skills(
        self, query: str, skills: list[Skill], max_skills: int = 5
    ) -> list[Skill]:
        """Select the most relevant skills for a user query.

        Matching strategy:
        1. Exact trigger match (query starts with a trigger phrase)
        2. Tag overlap between query tokens and skill tags
        3. If no match: return top skills by general relevance

        Args:
            query: User's message text.
            skills: Available skills to choose from.
            max_skills: Maximum number of skills to include.

        Returns:
            Ranked list of most relevant skills.
        """
        logger.info("skills.engine.select", query_length=len(query))
        # TODO: implement skill selection
        # 1. Check trigger matches: any(query.lower().startswith(t) for t in skill.triggers)
        # 2. Score by tag overlap with query tokens
        # 3. Sort by score, return top max_skills
        raise NotImplementedError("Skill selection not yet implemented")

    def build_prompt(self, skills: list[Skill]) -> str:
        """Build the skills section of the LLM system prompt.

        Formats selected skills as a structured prompt section that
        teaches the LLM what tools are available and how to use them.

        Args:
            skills: Selected skills to include.

        Returns:
            Formatted prompt string.
        """
        if not skills:
            return ""

        parts = ["## Available Skills\n"]
        for skill in skills:
            parts.append(f"### {skill.name}\n")
            parts.append(skill.content)
            parts.append("")

        return "\n".join(parts)

    async def seed_builtins(self) -> int:
        """Load builtin .md skill files into the database.

        Called during first migration / startup. Idempotent —
        uses upsert on (name, workspace_id=NULL).

        Returns:
            Number of skills seeded.
        """
        logger.info("skills.engine.seed_builtins")
        # TODO: implement builtin seeding
        # 1. Glob skills/builtin/*.md
        # 2. Parse each: name from filename, content from file
        # 3. Extract tags/triggers from frontmatter (if any)
        # 4. Upsert to DB via self._store.upsert_skill()
        raise NotImplementedError("Builtin seeding not yet implemented")
