"""Tool definitions for LLM function calling.

Defines the tools the LLM can invoke: knowledge_search, http_request,
exec_command. These definitions are passed to the LLM in OpenAI tool
format so it knows what tools are available and how to call them.
"""

from __future__ import annotations


def build_tool_definitions() -> list[dict[str, object]]:
    """Build the list of tool definitions for LLM function calling.

    Returns:
        List of tool dicts in OpenAI function calling format.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "knowledge_search",
                "description": (
                    "Search the team's indexed knowledge base. Use this when the user "
                    "asks a factual question about projects, documentation, or processes."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query reformulated for relevance",
                        },
                        "workspace_id": {
                            "type": "string",
                            "description": "Current workspace ID",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results to return (default: 5)",
                        },
                    },
                    "required": ["query", "workspace_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "http_request",
                "description": (
                    "Make an HTTP request to an allowed API endpoint. "
                    "Used for Jira, Confluence, GitHub API calls."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "method": {
                            "type": "string",
                            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                            "description": "HTTP method",
                        },
                        "url": {
                            "type": "string",
                            "description": "Full URL (must be on domain allowlist)",
                        },
                        "params": {
                            "type": "object",
                            "description": "URL query parameters",
                        },
                        "body": {
                            "type": "object",
                            "description": "Request body (JSON)",
                        },
                    },
                    "required": ["method", "url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "exec_command",
                "description": (
                    "Execute a shell command from the allowlist. "
                    "Only pre-approved commands can be run."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Command to execute (must be on allowlist)",
                        },
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Command arguments",
                        },
                    },
                    "required": ["command"],
                },
            },
        },
    ]
