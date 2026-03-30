"""Agent router — intent classification + dispatch.

The router receives user messages, classifies intent, and dispatches
to the appropriate handler: search, slash commands, greetings, or smalltalk.

AgentRouter.route() is SYNC because hybrid_search_and_answer() and
chat_completion() are both sync. Telegram calls it via asyncio.to_thread().
"""

from __future__ import annotations

import asyncio
from enum import StrEnum

import structlog

from metatron.agent.sessions import SessionManager
from metatron.core.config import Settings
from metatron.llm import chat_completion
from metatron.llm.base import LLMError
from metatron.retrieval.search import hybrid_search_and_answer_sync

try:
    from httpx import ConnectError as HttpxConnectError
except ImportError:  # pragma: no cover
    HttpxConnectError = None  # type: ignore[assignment,misc]

try:
    from qdrant_client.http.exceptions import (
        ResponseHandlingException as QdrantResponseHandlingException,
    )
except ImportError:  # pragma: no cover
    QdrantResponseHandlingException = None  # type: ignore[assignment,misc]

try:
    from neo4j.exceptions import ServiceUnavailable as Neo4jServiceUnavailable
except ImportError:  # pragma: no cover
    Neo4jServiceUnavailable = None  # type: ignore[assignment,misc]

logger = structlog.get_logger()

_GREETING_WORDS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "привет",
        "здравствуйте",
        "добрый день",
        "добрый вечер",
        "доброе утро",
        "хай",
        "хей",
        "yo",
        "sup",
        "good morning",
        "good evening",
        "good afternoon",
    }
)

_SMALLTALK_PATTERNS = frozenset(
    {
        "how are you",
        "как дела",
        "что нового",
        "what's up",
        "who are you",
        "кто ты",
        "what can you do",
        "что ты умеешь",
        "thanks",
        "спасибо",
        "thank you",
        "благодарю",
    }
)


_ACTION_KEYWORDS_EN = frozenset(
    {
        "create",
        "make",
        "file",
        "open",
        "send",
        "post",
        "update",
        "add comment",
        "write",
        "submit",
        "publish",
    }
)

_ACTION_KEYWORDS_RU = frozenset(
    {
        "создай",
        "создать",
        "заведи",
        "завести",
        "добавь",
        "добавить",
        "отправь",
        "отправить",
        "напиши",
        "написать",
        "обнови",
        "обновить",
        "прокомментируй",
        "опубликуй",
        "опубликовать",
    }
)

_CONFIRMATION_YES = frozenset(
    {
        "да",
        "yes",
        "y",
        "д",
        "ок",
        "ok",
        "подтверждаю",
        "confirm",
    }
)
_CONFIRMATION_NO = frozenset(
    {
        "нет",
        "no",
        "n",
        "отмена",
        "cancel",
        "отменить",
    }
)

_CONTEXT_KEYWORDS = frozenset(
    {
        "итоги",
        "summary",
        "отчёт",
        "отчет",
        "report",
        "результаты",
        "results",
        "обзор",
        "overview",
    }
)


class Intent(StrEnum):
    """Classified intent for an incoming message."""

    SEARCH = "search"
    GREETING = "greeting"
    SMALLTALK = "smalltalk"
    COMMAND = "command"
    ACTION = "action"


class AgentRouter:
    """Routes incoming messages through intent classification + dispatch.

    Flow:
    1. Slash commands (/search, /sync, /status, /help, /clear) → command handler
    2. Greetings → greeting handler
    3. Smalltalk → LLM smalltalk handler
    4. Everything else → search (hybrid_search_and_answer)

    All methods are SYNC. Telegram calls route() via asyncio.to_thread().
    """

    def __init__(
        self,
        settings: Settings | None = None,
        sessions: SessionManager | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._sessions = sessions or SessionManager.get_instance()

    def route(
        self,
        text: str,
        user_id: str,
        workspace_id: str | None = None,
    ) -> str:
        """Route a message and return the response text.

        Args:
            text: User message text.
            user_id: Channel-specific user ID.
            workspace_id: Workspace scope (defaults to settings.default_workspace_id).

        Returns:
            Response text string.
        """
        ws = workspace_id or self._settings.default_workspace_id
        text = text.strip()

        if not text:
            return "Please send a message or type /help for available commands."

        # Check for pending action confirmation before classifying
        confirmation_result = self._check_confirmation(text, user_id, ws)
        if confirmation_result is not None:
            return confirmation_result

        logger.info("router.route", user_id=user_id, workspace_id=ws, text_len=len(text))

        intent = self._classify(text)
        logger.info("router.intent", intent=intent, text_preview=text[:80])

        try:
            if intent == Intent.COMMAND:
                return self._handle_command(text, user_id, ws)
            if intent == Intent.GREETING:
                return self._handle_greeting(user_id, ws)
            if intent == Intent.SMALLTALK:
                return self._handle_smalltalk(text, user_id, ws)
            if intent == Intent.ACTION:
                return self._handle_action(text, user_id, ws)
            return self._handle_search(text, user_id, ws)
        except LLMError as e:
            logger.error("router.error.llm", intent=intent, error=str(e), exc_info=True)
            return "AI service is temporarily unavailable. Please try again later."
        except Exception as e:
            if (HttpxConnectError and isinstance(e, HttpxConnectError)) or (
                QdrantResponseHandlingException and isinstance(e, QdrantResponseHandlingException)
            ):
                logger.error(
                    "router.error.search_service", intent=intent, error=str(e), exc_info=True
                )
                return "Search service is temporarily unavailable. Please try again later."
            if Neo4jServiceUnavailable and isinstance(e, Neo4jServiceUnavailable):
                logger.error("router.error.graph", intent=intent, error=str(e), exc_info=True)
                return "Knowledge graph is temporarily unavailable. Please try again later."
            logger.error("router.error", intent=intent, error=str(e), exc_info=True)
            return "Something went wrong. The error has been logged."

    def _classify(self, text: str) -> Intent:
        """Classify the intent of a message."""
        lower = text.lower().strip()

        if lower.startswith("/") or lower.startswith("!"):
            return Intent.COMMAND

        if lower in _GREETING_WORDS or lower.rstrip("!") in _GREETING_WORDS:
            return Intent.GREETING

        for pattern in _SMALLTALK_PATTERNS:
            if lower.startswith(pattern):
                return Intent.SMALLTALK

        # Detect action intent (create/update/send requests)
        for kw in _ACTION_KEYWORDS_RU:
            if kw in lower:
                return Intent.ACTION
        for kw in _ACTION_KEYWORDS_EN:
            if kw in lower:
                return Intent.ACTION

        return Intent.SEARCH

    def _handle_search(self, text: str, user_id: str, workspace_id: str) -> str:
        """Handle a search query via hybrid_search_and_answer."""
        # Build composite query from conversation context
        composite = self._sessions.build_composite_query(user_id, workspace_id, text)

        logger.info("router.search", user_id=user_id, composite_len=len(composite))

        # Record user turn
        self._sessions.add_turn(user_id, workspace_id, "user", text)

        # Call existing search pipeline
        # query = composite (with history context for richer search)
        # intent_query = text (current question only — for language detection)
        answer = hybrid_search_and_answer_sync(
            query=composite,
            user_id=user_id,
            workspace_id=workspace_id,
            intent_query=text,
        )

        # Record assistant turn
        self._sessions.add_turn(user_id, workspace_id, "assistant", answer)

        return answer

    def _check_confirmation(
        self,
        text: str,
        user_id: str,
        workspace_id: str,
    ) -> str | None:
        """Check if user is confirming/cancelling a pending action.

        Returns response string if handled, None to continue normal routing.
        """
        from metatron.mcp.action_store import get_action_store

        store = get_action_store()
        pending = store.get_for_user(user_id)
        if not pending:
            return None

        text_lower = text.lower().strip()

        if text_lower in _CONFIRMATION_YES:
            from metatron.mcp.action_executor import ActionExecutor

            executor = ActionExecutor()
            result = executor.execute(pending)
            store.remove(pending.action_id)
            if result["success"]:
                return f"Done: {pending.description}\n\n{result['result']}"
            return f"Error: {result['error']}"

        if text_lower in _CONFIRMATION_NO:
            store.remove(pending.action_id)
            return "Action cancelled."

        # Not a confirmation — fall through to normal routing
        # (remove stale pending so it doesn't block future messages)
        return None

    def _handle_action(self, text: str, user_id: str, workspace_id: str) -> str:
        """Handle an action request — plan via LLM, store for confirmation."""
        from metatron.mcp.action_planner import ActionPlanner, ActionPolicy
        from metatron.mcp.action_store import PendingAction, get_action_store

        planner = ActionPlanner()
        write_tools = planner.discover_write_tools(workspace_id)

        if not write_tools:
            # No write tools available — fall through to search
            logger.info("router.action.no_tools", text_preview=text[:80])
            return self._handle_search(text, user_id, workspace_id)

        # Check if action needs knowledge base context
        context = ""
        lower = text.lower()
        if any(kw in lower for kw in _CONTEXT_KEYWORDS):
            try:
                context = hybrid_search_and_answer_sync(
                    query=text,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    intent_query=text,
                )
            except Exception as e:
                logger.warning("router.action.context_error", error=str(e))

        plan = planner.plan(text, write_tools, context=context)

        if "error" in plan:
            suggestion = plan.get("suggestion", "")
            return f"{plan['error']}\n{suggestion}".strip()

        # Check policy
        if not ActionPolicy.is_allowed(user_id, plan.get("tool", "")):
            return "You don't have permission to perform this action."

        # Store pending action for confirmation
        action = PendingAction(
            user_id=user_id,
            server_name=plan.get("server", ""),
            tool_name=plan.get("tool", ""),
            arguments=plan.get("arguments", {}),
            description=plan.get("description", "Action"),
            preview=plan.get("preview", ""),
        )
        store = get_action_store()
        store.add(action)

        # Return confirmation prompt
        preview = action.preview or "(no preview)"
        return f"**{action.description}**\n\n{preview}\n\nConfirm? (Yes/No)"

    # -- Supported upload formats --
    SUPPORTED_UPLOAD_EXTENSIONS: frozenset[str] = frozenset(
        {
            ".txt",
            ".md",
            ".html",
            ".htm",
            ".csv",
            ".xlsx",
            ".xls",
            ".pdf",
        }
    )
    _MAX_UPLOAD_BYTES: int = 20 * 1024 * 1024  # 20 MB

    def handle_file_upload(
        self,
        content: bytes,
        filename: str,
        user_id: str,
        workspace_id: str | None = None,
    ) -> str:
        """Process an uploaded file through the ingestion pipeline.

        Args:
            content: Raw file bytes.
            filename: Original filename (used for format detection + title).
            user_id: Channel-specific user ID.
            workspace_id: Workspace scope.

        Returns:
            User-facing result message.
        """
        from pathlib import Path

        from metatron.core.models import Document
        from metatron.ingestion.pipeline import ingest_documents

        ws = workspace_id or self._settings.default_workspace_id
        ext = Path(filename).suffix.lower()

        if ext not in self.SUPPORTED_UPLOAD_EXTENSIONS:
            return (
                f"Unsupported file type: {ext}\n"
                f"Supported: {', '.join(sorted(self.SUPPORTED_UPLOAD_EXTENSIONS))}"
            )

        if len(content) > self._MAX_UPLOAD_BYTES:
            return "File too large. Maximum size is 20 MB."

        logger.info("router.upload", filename=filename, size=len(content), user_id=user_id)

        try:
            text = self._parse_upload(content, filename, ext)
        except Exception as e:
            logger.warning("router.upload.parse_error", filename=filename, error=str(e))
            return f"Could not parse {filename}. Please check the file format."

        if not text or len(text.strip()) < 10:
            return f"File {filename} appears to be empty or too short."

        title = self._extract_title_from_content(text, filename)
        source_id = f"upload:{filename}"
        doc = Document(
            source_type="upload",
            source_id=source_id,
            workspace_id=ws,
            title=title,
            content=text,
            author=user_id,
            metadata={"type": "upload", "filename": filename},
        )

        try:
            result = asyncio.run(
                ingest_documents(
                    [doc],
                    ws,
                    connector_type="upload",
                    incremental=True,
                )
            )
        except Exception as e:
            logger.error(
                "router.upload.ingest_error", filename=filename, error=str(e), exc_info=True
            )
            return f"Error processing {filename}. The error has been logged."

        parts = []
        if result.documents_new:
            parts.append(f"{result.documents_new} new")
        if result.documents_updated:
            parts.append(f"{result.documents_updated} updated")
        if result.errors:
            parts.append(f"{len(result.errors)} errors")

        return f"Indexed {filename}: {', '.join(parts) or 'processed'}."

    def _parse_upload(self, content: bytes, filename: str, ext: str) -> str:
        """Parse uploaded file bytes into text based on extension."""
        if ext == ".pdf":
            from metatron.ingestion.processors.pdf import extract_text_from_pdf

            return extract_text_from_pdf(content, filename)

        if ext in (".txt", ".md"):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                return content.decode("latin-1")

        if ext in (".html", ".htm"):
            from metatron.ingestion.processors.html import process_html

            return process_html(content)

        if ext in (".csv", ".xlsx", ".xls"):
            from metatron.ingestion.processors.tabular import process_tabular_file

            text, _meta = process_tabular_file(content, filename)
            return text

        return ""

    @staticmethod
    def _extract_title_from_content(text: str, filename: str) -> str:
        """Extract a meaningful title from file content, fallback to filename."""
        for line in text.strip().split("\n")[:5]:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                if title:
                    return title
                continue
            if 5 < len(line) < 200:
                return line
        return filename

    def _handle_greeting(self, user_id: str, workspace_id: str) -> str:
        """Handle a greeting message."""
        return (
            "Hello! I'm Metatron, your team's knowledge assistant.\n\n"
            "Ask me anything about your project, or use /help to see available commands."
        )

    def _handle_smalltalk(self, text: str, user_id: str, workspace_id: str) -> str:
        """Handle smalltalk via LLM."""
        try:
            answer = chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Metatron, a helpful AI knowledge assistant for teams. "
                            "Reply briefly and friendly. Keep answers to 1-2 sentences."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0.7,
                max_tokens=150,
                timeout=15,
            )
            return answer.strip()
        except Exception as e:
            logger.warning("router.smalltalk.llm_failed", error=str(e))
            return "I'm Metatron, your team's knowledge assistant. How can I help?"

    def _handle_command(self, text: str, user_id: str, workspace_id: str) -> str:
        """Handle slash/bang commands (e.g. /help or !help)."""
        # Normalize: !command → /command
        normalized = text.strip()
        if normalized.startswith("!"):
            normalized = "/" + normalized[1:]

        parts = normalized.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command == "/help":
            return self._cmd_help()
        if command == "/search":
            if not arg:
                return "Usage: /search <query>"
            return self._handle_search(arg, user_id, workspace_id)
        if command == "/sync":
            return self._cmd_sync(arg or None, workspace_id)
        if command == "/status":
            return self._cmd_status(workspace_id)
        if command == "/clear":
            self._sessions.clear(user_id, workspace_id)
            return "Conversation history cleared."
        if command == "/start":
            return self._handle_greeting(user_id, workspace_id)
        if command == "/rebuild-aliases":
            return self._cmd_rebuild_aliases(workspace_id)
        if command == "/mcp":
            return self._cmd_mcp(arg, workspace_id)

        return f"Unknown command: {command}. Type /help for available commands."

    def _cmd_help(self) -> str:
        """Return help text with available commands."""
        return (
            "**Available commands:**\n"
            "/search <query> — Search the knowledge base\n"
            "/sync confluence|jira|notion — Incremental sync (only changes)\n"
            "/sync confluence|jira|notion full — Full re-sync from scratch\n"
            "/mcp list — List configured MCP servers\n"
            "/mcp add <name> <command> [args...] — Add MCP server\n"
            "/mcp remove <name> — Remove MCP server\n"
            "/mcp sync <name> [full] — Sync one MCP server\n"
            "/mcp sync-all [full] — Sync all MCP servers\n"
            "/mcp tools <name> — List tools from MCP server\n"
            "/status — Show workspace status\n"
            "/clear — Clear conversation history\n"
            "/rebuild-aliases — Rebuild person name registry from stored data\n"
            "/help — Show this help message\n\n"
            "You can also use ! instead of / (e.g. !help, !sync).\n\n"
            "Or just type your question and I'll search for the answer.\n"
            "To perform actions (create issues, pages, etc.), just describe what you want."
        )

    def _cmd_mcp(self, arg: str, workspace_id: str) -> str:
        """Handle /mcp subcommands: list, add, remove, sync, sync-all, tools."""
        from metatron.mcp.config import MCPServerConfig
        from metatron.mcp.registry import MCPServerRegistry

        parts = arg.split() if arg else []
        subcmd = parts[0].lower() if parts else "list"
        rest = parts[1:]

        registry = MCPServerRegistry()

        if subcmd == "list":
            servers = registry.list_servers(workspace_id)
            if not servers:
                return "No MCP servers configured. Use /mcp add <name> <command> [args...]"
            lines = ["**MCP servers:**"]
            for s in servers:
                status = "enabled" if s.enabled else "disabled"
                cmd = f"{s.command} {' '.join(s.args)}".strip()
                lines.append(f"- **{s.name}** ({status}): `{cmd}`")
                if s.description:
                    lines.append(f"  {s.description}")
            return "\n".join(lines)

        if subcmd == "add":
            if len(rest) < 2:
                return "Usage: /mcp add <name> <command> [args...]"
            name = rest[0]
            command = rest[1]
            args = rest[2:]
            config = MCPServerConfig(
                name=name,
                command=command,
                args=args,
                workspace_id=workspace_id,
            )
            registry.add(config)
            return f"MCP server **{name}** added: `{command} {' '.join(args)}`"

        if subcmd == "remove":
            if not rest:
                return "Usage: /mcp remove <name>"
            name = rest[0]
            if registry.remove(name):
                return f"MCP server **{name}** removed."
            return f"MCP server **{name}** not found."

        if subcmd == "sync":
            if not rest:
                return "Usage: /mcp sync <server_name> [full]"
            name = rest[0]
            force_full = "full" in rest[1:]
            config = registry.get(name)
            if not config:
                return f"MCP server **{name}** not found. Use /mcp list to see available."
            return self._run_mcp_sync(config, workspace_id, force_full)

        if subcmd == "sync-all":
            force_full = "full" in rest
            return self._run_mcp_sync_all(workspace_id, force_full, registry)

        if subcmd == "tools":
            if not rest:
                return "Usage: /mcp tools <server_name>"
            name = rest[0]
            config = registry.get(name)
            if not config:
                return f"MCP server **{name}** not found."
            return self._run_mcp_list_tools(config)

        return f"Unknown /mcp subcommand: {subcmd}. Try /mcp list"

    def _run_mcp_sync(
        self,
        config: MCPServerConfig,
        workspace_id: str,
        force_full: bool,
    ) -> str:
        """Run sync for a single MCP server (sync wrapper)."""
        from metatron.mcp.sync import MCPSyncManager

        manager = MCPSyncManager()
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(manager.sync_server(config, workspace_id, force_full))
        except Exception as e:
            logger.error("router.mcp_sync.error", server=config.name, error=str(e), exc_info=True)
            return f"MCP sync error for **{config.name}**: {e}"
        finally:
            loop.close()

        parts_msg = []
        if result.documents_new:
            parts_msg.append(f"{result.documents_new} new")
        if result.documents_updated:
            parts_msg.append(f"{result.documents_updated} updated")
        if result.documents_skipped:
            parts_msg.append(f"{result.documents_skipped} unchanged")
        if result.errors:
            parts_msg.append(f"{len(result.errors)} errors")
        mode = "full" if force_full else "incremental"
        return f"**{config.name}** ({mode}): {', '.join(parts_msg) or 'no documents'}"

    def _run_mcp_sync_all(
        self,
        workspace_id: str,
        force_full: bool,
        registry: MCPServerRegistry,
    ) -> str:
        """Run sync for all enabled MCP servers (sync wrapper)."""
        from metatron.mcp.sync import MCPSyncManager

        manager = MCPSyncManager(registry)
        loop = asyncio.new_event_loop()
        try:
            results = loop.run_until_complete(manager.sync_all(workspace_id, force_full))
        except Exception as e:
            logger.error("router.mcp_sync_all.error", error=str(e), exc_info=True)
            return f"MCP sync-all error: {e}"
        finally:
            loop.close()

        if not results:
            return "No enabled MCP servers found."

        lines = ["**MCP sync complete:**"]
        for name, result in results:
            parts_msg = []
            if result.documents_new:
                parts_msg.append(f"{result.documents_new} new")
            if result.documents_updated:
                parts_msg.append(f"{result.documents_updated} updated")
            if result.documents_skipped:
                parts_msg.append(f"{result.documents_skipped} unchanged")
            if result.errors:
                parts_msg.append(f"{len(result.errors)} errors")
            lines.append(f"- **{name}**: {', '.join(parts_msg) or 'no documents'}")
        return "\n".join(lines)

    def _run_mcp_list_tools(self, config: MCPServerConfig) -> str:
        """List tools from an MCP server (sync wrapper)."""
        from metatron.mcp.adapter import classify_tool
        from metatron.mcp.client import MCPClient

        loop = asyncio.new_event_loop()
        try:

            async def _list() -> list[dict]:
                async with MCPClient(config) as client:
                    return await client.list_tools()

            tools = loop.run_until_complete(_list())
        except Exception as e:
            logger.error("router.mcp_tools.error", server=config.name, error=str(e), exc_info=True)
            return f"Cannot connect to **{config.name}**: {e}"
        finally:
            loop.close()

        if not tools:
            return f"**{config.name}**: no tools available."

        lines = [f"**{config.name}** — {len(tools)} tools:"]
        for t in tools:
            kind = classify_tool(t["name"], t.get("description", ""))
            desc = t.get("description", "")[:80]
            lines.append(f"- `{t['name']}` [{kind}] — {desc}")
        return "\n".join(lines)

    def _cmd_sync(self, arg: str | None, workspace_id: str) -> str:
        """Trigger a connector sync. Now uses DB-based connections.

        Usage:
            /sync              — sync all enabled connections
            /sync confluence   — sync connections of type confluence
            /sync confluence full — full sync (ignores last sync time)
        """
        return (
            "Sync via chat is no longer supported. Use the API: POST /api/v1/connections/{id}/sync"
        )

    def _cmd_status(self, workspace_id: str) -> str:
        """Show workspace status — Qdrant point count, LLM provider."""
        lines = [f"**Workspace:** {workspace_id}"]

        # Qdrant stats
        try:
            from metatron.storage.qdrant import get_hybrid_store

            store = get_hybrid_store(workspace_id)
            count = store.client.count(collection_name=store.collection_name).count
            lines.append(f"**Qdrant points:** {count}")
        except Exception as e:
            lines.append(f"**Qdrant:** unavailable ({e})")

        lines.append("**Connectors:** managed via API (GET /api/v1/connections)")

        # LLM provider
        lines.append(f"**LLM provider:** {self._settings.llm_provider}")
        if self._settings.llm_fallback_provider:
            lines.append(f"**LLM fallback:** {self._settings.llm_fallback_provider}")

        return "\n".join(lines)

    def _cmd_rebuild_aliases(self, workspace_id: str) -> str:
        """Rebuild person alias registry by scanning existing Qdrant data."""
        from metatron.retrieval.alias_registry import get_alias_registry
        from metatron.retrieval.aliases import seed_custom_aliases
        from metatron.storage.qdrant import get_hybrid_store

        registry = get_alias_registry()

        # Seed hardcoded aliases first (idempotent)
        seed_custom_aliases(registry)

        try:
            store = get_hybrid_store(workspace_id)
            added = registry.populate_from_qdrant(store)
        except Exception as e:
            logger.error("router.rebuild_aliases.error", error=str(e), exc_info=True)
            return "Failed to scan Qdrant: the error has been logged."

        return f"Alias registry rebuilt: {added} new persons found, {registry.person_count} total."
