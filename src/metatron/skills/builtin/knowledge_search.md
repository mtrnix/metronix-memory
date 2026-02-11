# Knowledge Search

Search the team's indexed knowledge base for answers to questions.

## When to use
- User asks a factual question about projects, processes, or documentation
- User needs information that might be in Confluence, Notion, or uploaded documents
- Query contains phrases like "what is", "how to", "where can I find"

## Triggers
- search
- find
- what is
- how to

## Tags
- knowledge
- search
- documentation
- wiki

## Tool Call

```json
{
  "tool": "knowledge_search",
  "parameters": {
    "query": "<reformulated search query>",
    "workspace_id": "<current workspace>",
    "top_k": 5
  }
}
```

## Behavior
1. Reformulate the user's question into an effective search query
2. Call the knowledge_search tool with the query
3. Review the returned context chunks
4. Synthesize an answer using ONLY the retrieved context
5. Always cite the source document (title + URL) for each fact
6. If no relevant results found, say so clearly — do not hallucinate

## Response Format
- Lead with a direct answer
- Follow with supporting details from sources
- End with source citations as links
