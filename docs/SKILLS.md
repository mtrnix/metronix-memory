# Skills

## Overview

Skills are Markdown documents that teach the LLM how to use tools. They contain instructions, examples, and structured tool call formats that the LLM reads at runtime to decide what actions to take.

Skills are stored in PostgreSQL (not as files) to enable CRUD operations via API and workspace-specific customization.

## What Skills Are

A skill is a structured knowledge artifact with:

- **Name**: Unique identifier (e.g., `knowledge_search`)
- **Description**: One-line summary of what the skill does
- **Content**: Markdown document with instructions and tool call examples
- **Tags**: List of keywords for categorization (e.g., `["search", "knowledge"]`)
- **Triggers**: Keywords or patterns that suggest when to activate this skill (e.g., `["search", "find", "lookup"]`)

Skills do not contain code. They are purely declarative: they describe how to use a tool, and the LLM interprets them at runtime.

## Builtin Skills

Metatron ships with four builtin skills in `src/skills/builtin/`:

### 1. knowledge_search

**File**: `knowledge_search.md`

**Purpose**: Search the knowledge base for relevant documents

**Triggers**: `search`, `find`, `lookup`, `show me`, `what do we know about`

**Tool Call Format**:
```json
{
  "tool": "knowledge_search",
  "parameters": {
    "query": "user's search query",
    "workspace_id": "uuid",
    "limit": 10
  }
}
```

**What It Teaches**:
- When to search (user asks a question, references documentation, etc.)
- How to formulate queries (extract key terms, remove stop words)
- How to interpret results (relevance scores, metadata)

### 2. jira_actions

**File**: `jira_actions.md`

**Purpose**: Create, update, search, and comment on Jira issues

**Triggers**: `jira`, `ticket`, `issue`, `create issue`, `update status`, `assign to`

**Tool Call Format**:
```json
{
  "tool": "jira_create_issue",
  "parameters": {
    "project_key": "PROJ",
    "summary": "Issue title",
    "description": "Issue body",
    "issue_type": "Task"
  }
}
```

**What It Teaches**:
- Available Jira operations (create, update, search, comment, transition)
- Required fields for each operation
- How to extract parameters from natural language (e.g., "assign to Alice" -> `{"assignee": "alice"}`)

### 3. github_actions

**File**: `github_actions.md`

**Purpose**: Create issues, PRs, comments, and search GitHub

**Triggers**: `github`, `gh`, `create issue`, `open pr`, `merge`, `code review`

**Tool Call Format**:
```json
{
  "tool": "github_create_issue",
  "parameters": {
    "repo": "owner/repo",
    "title": "Issue title",
    "body": "Issue description",
    "labels": ["bug", "high-priority"]
  }
}
```

**What It Teaches**:
- GitHub operations (issues, PRs, comments, reviews)
- Repository naming format (`owner/repo`)
- How to infer repo from context if not specified

### 4. confluence_actions

**File**: `confluence_actions.md`

**Purpose**: Create, update, and search Confluence pages

**Triggers**: `confluence`, `wiki`, `create page`, `update documentation`, `document this`

**Tool Call Format**:
```json
{
  "tool": "confluence_create_page",
  "parameters": {
    "space_key": "SPACE",
    "title": "Page Title",
    "content": "Markdown or HTML content",
    "parent_page_id": "optional-parent-id"
  }
}
```

**What It Teaches**:
- Confluence operations (create, update, search)
- Space key and page ID concepts
- Content format (Confluence storage format vs Markdown)

## How the LLM Uses Skills

### Skill Selection Flow

1. **User Message Arrives**: System receives a user query
2. **SkillEngine Analyzes**: `SkillEngine.select_relevant_skills(query, workspace_id)` runs
3. **Trigger Matching**: Skills whose triggers appear in the query are scored
4. **Context Matching**: Vector similarity between query and skill descriptions is computed
5. **Top Skills Selected**: Top N skills (default: 3) are selected
6. **System Prompt Built**: Selected skills are injected into the system prompt
7. **LLM Reads Skills**: LLM reads skill content and decides what tools to call
8. **Tool Calls Executed**: LLM outputs structured tool calls, which are executed by `ToolExecutor`

### Example: User Query to Tool Call

**User**: "Find me all documents about our authentication system"

**System**:
1. SkillEngine finds `knowledge_search` skill (trigger: "find")
2. Skill content is added to system prompt
3. LLM reads skill instructions
4. LLM outputs:
   ```json
   {
     "tool": "knowledge_search",
     "parameters": {
       "query": "authentication system",
       "workspace_id": "workspace-uuid",
       "limit": 10
     }
   }
   ```
5. ToolExecutor calls the knowledge search function
6. Results are returned to LLM, which formats a response for the user

## Skill Format

Skills are written in Markdown with specific sections:

```markdown
# Skill Name

## Description
One-line summary of what this skill does.

## When to Use
- Use case 1
- Use case 2
- Use case 3

## Tool Call Format

Provide the exact JSON structure:

\`\`\`json
{
  "tool": "tool_name",
  "parameters": {
    "param1": "description",
    "param2": "description"
  }
}
\`\`\`

## Parameters

- `param1` (required): Description
- `param2` (optional): Description, default value

## Examples

### Example 1: Use Case A
User: "Example user message"

Tool call:
\`\`\`json
{
  "tool": "tool_name",
  "parameters": {
    "param1": "value1",
    "param2": "value2"
  }
}
\`\`\`

### Example 2: Use Case B
User: "Another example"

Tool call:
\`\`\`json
{
  "tool": "tool_name",
  "parameters": {
    "param1": "different-value"
  }
}
\`\`\`

## Error Handling

What to do if:
- Required parameters are missing -> ask the user
- Tool call fails -> graceful degradation strategy
- Multiple interpretations -> clarify with user

## Notes

Additional context, gotchas, best practices.
```

## Writing a Custom Skill

### Step 1: Create the Markdown File

Create `src/skills/builtin/my_custom_skill.md`:

```markdown
# My Custom Skill

## Description
Summarize long documents into key points.

## When to Use
- User asks for a summary of a document
- User says "tl;dr", "summarize", "give me the highlights"
- User references a specific document and wants condensed info

## Tool Call Format

\`\`\`json
{
  "tool": "summarize_document",
  "parameters": {
    "document_id": "uuid",
    "max_sentences": 5,
    "focus_area": "optional keyword"
  }
}
\`\`\`

## Parameters

- `document_id` (required): UUID of the document to summarize
- `max_sentences` (optional): Maximum number of sentences in summary, default 5
- `focus_area` (optional): Specific topic to focus on (e.g., "security", "performance")

## Examples

### Example 1: Basic Summary
User: "Can you summarize document abc-123?"

Tool call:
\`\`\`json
{
  "tool": "summarize_document",
  "parameters": {
    "document_id": "abc-123",
    "max_sentences": 5
  }
}
\`\`\`

### Example 2: Focused Summary
User: "Summarize the security aspects of document xyz-456"

Tool call:
\`\`\`json
{
  "tool": "summarize_document",
  "parameters": {
    "document_id": "xyz-456",
    "max_sentences": 5,
    "focus_area": "security"
  }
}
\`\`\`

## Error Handling

- If `document_id` is missing, search for documents matching the user's description first
- If document does not exist, inform user and offer to search
- If document is too short to summarize (< 3 sentences), return full text

## Notes

Summaries preserve key facts and actionable items. Technical terms are not simplified.
```

### Step 2: Define Triggers and Tags

Add metadata to the skill in the database seed script (`scripts/seed_skills.py`):

```python
skills.append({
    "name": "my_custom_skill",
    "description": "Summarize long documents into key points",
    "content": read_skill_file("my_custom_skill.md"),
    "tags": ["summarization", "documents", "nlp"],
    "triggers": ["summarize", "tl;dr", "highlights", "key points", "condense"],
    "is_builtin": True
})
```

### Step 3: Implement the Tool

Create the actual tool function in `src/tools/`:

```python
from typing import Dict, Any
import structlog

logger = structlog.get_logger()

async def summarize_document(
    document_id: str,
    max_sentences: int = 5,
    focus_area: Optional[str] = None
) -> Dict[str, Any]:
    """Summarize a document."""
    logger.info("summarize_document_called", document_id=document_id)

    # Fetch document
    doc = await fetch_document(document_id)
    if not doc:
        return {"error": "Document not found"}

    # Generate summary
    summary = await generate_summary(
        doc.content,
        max_sentences=max_sentences,
        focus_area=focus_area
    )

    return {
        "document_id": document_id,
        "summary": summary,
        "original_length": len(doc.content),
        "summary_length": len(summary)
    }
```

### Step 4: Register the Tool

Add to `src/tools/registry.py`:

```python
from src.tools.summarization import summarize_document

TOOL_REGISTRY = {
    "knowledge_search": knowledge_search,
    "jira_create_issue": jira_create_issue,
    "github_create_issue": github_create_issue,
    "confluence_create_page": confluence_create_page,
    "summarize_document": summarize_document,  # Add here
}
```

## Skill Lifecycle

### 1. Development (Markdown Files)

Skills are authored as `.md` files in `src/skills/builtin/`:

```
src/skills/builtin/
  knowledge_search.md
  jira_actions.md
  github_actions.md
  confluence_actions.md
  my_custom_skill.md
```

### 2. Database Seeding (First Migration)

When the database is initialized, skills are seeded from Markdown files:

```bash
make migrate  # Runs alembic migrations + seeds skills
```

The seed script (`scripts/seed_skills.py`) reads `.md` files and inserts them into the `skills` table.

### 3. Runtime (Database)

At runtime, the LLM reads skills from the database, not from files:

```python
skills = await SkillRepository.get_by_workspace(workspace_id)
```

This enables:
- Workspace-specific skill customization
- CRUD operations via API
- Version control (skill updates without redeployment)

### 4. CRUD via API

Skills can be managed via REST API:

```bash
# List skills
GET /api/v1/skills?workspace_id=uuid

# Get a skill
GET /api/v1/skills/{skill_id}

# Create custom skill
POST /api/v1/skills
{
  "name": "custom_skill",
  "description": "...",
  "content": "markdown content",
  "tags": ["tag1", "tag2"],
  "triggers": ["trigger1", "trigger2"],
  "workspace_id": "uuid"
}

# Update skill
PUT /api/v1/skills/{skill_id}
{
  "content": "updated markdown"
}

# Delete skill
DELETE /api/v1/skills/{skill_id}
```

## Skill Selection Algorithm

`SkillEngine.select_relevant_skills()` uses a hybrid approach:

1. **Trigger Matching**: Exact or fuzzy match on trigger keywords (weight: 0.4)
2. **Vector Similarity**: Cosine similarity between query embedding and skill description embedding (weight: 0.6)
3. **Scoring**: Combine scores, sort, return top N skills
4. **Caching**: Skill embeddings are cached in memory to avoid re-embedding on every query

Example:

```python
# User query: "Show me all recent Jira tickets"
# Triggers matched: "jira", "tickets" (jira_actions skill)
# Vector similarity: high for jira_actions, low for github_actions
# Result: jira_actions skill selected, added to system prompt
```

## Best Practices

1. **Be Specific**: Include detailed examples covering edge cases
2. **Error Handling**: Teach the LLM how to recover from missing parameters or failures
3. **One Tool per Skill**: Each skill should teach one tool (or one family of related tools)
4. **Natural Language Triggers**: Use phrases users actually say, not technical jargon
5. **JSON Accuracy**: Ensure tool call JSON is valid and matches function signatures
6. **Concise Descriptions**: Keep descriptions under 100 characters for better embedding
7. **Progressive Detail**: Start with a simple example, then show advanced usage
8. **Testing**: Test skills with real user queries to ensure LLM interprets them correctly

## Troubleshooting

**Skill not being selected**:
- Check that triggers match user query terms
- Verify skill description is semantically similar to user intent
- Increase skill selection threshold or top N limit

**LLM not following skill format**:
- Simplify the tool call JSON structure
- Add more examples showing the exact format
- Use explicit instruction language ("You MUST use this format:")

**Tool call fails**:
- Verify tool function signature matches skill parameter list
- Check that tool is registered in `TOOL_REGISTRY`
- Review tool function logs for errors
