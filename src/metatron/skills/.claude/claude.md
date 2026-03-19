# Skills

## Overview
L3 — skill engine for teaching the LLM how to use tools. Skills are Markdown documents
stored in PostgreSQL. `SkillEngine` loads, selects, and formats them for LLM context injection.

## Files

### `engine.py`
`SkillEngine(postgres_store: PostgresStore)` — manages skill lifecycle.

`load_skills(workspace_id) -> list[Skill]`
— **NotImplementedError** (not yet implemented). Intended to fetch skills from PostgreSQL
filtered by workspace_id + global skills (workspace_id=None).

`select_skills(query, skills) -> list[Skill]`
— **NotImplementedError**. Intended to rank skills by relevance to query using trigger matching.

`build_prompt(skills: list[Skill]) -> str`
— **Implemented**. Formats skill list as Markdown:
```markdown
## Available Skills

### {skill.name}
{skill.content}

### {skill.name}
{skill.content}
```

`seed_builtins(workspace_id)`
— Seeds built-in skills from `skills/builtin/*.md` glob (directory doesn't exist yet — future).

### `builtin/`
Directory for built-in skill Markdown files. Currently empty / not created.
Future: `*.md` files here get loaded by `seed_builtins()` on first migration.

## Key Patterns
- **Skills as Markdown** — `Skill.content` is raw Markdown injected into LLM system prompt
- **Global vs workspace skills** — `workspace_id=None` means skill is available to all workspaces
- **`builtin: bool` flag** — built-in skills are not deletable via API

## Dependencies
- **Depends on**: `core.models` (Skill), `storage.postgres` (PostgresStore)
- **Depended on by**: `api.routes.skills`, `agent.router` (skill context injection into LLM calls)
