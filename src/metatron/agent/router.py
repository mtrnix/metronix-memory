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
from metatron.retrieval.search import hybrid_search_and_answer

logger = structlog.get_logger()

_GREETING_WORDS = frozenset({
    "hi", "hello", "hey", "привет", "здравствуйте", "добрый день",
    "добрый вечер", "доброе утро", "хай", "хей", "yo", "sup",
    "good morning", "good evening", "good afternoon",
})

_SMALLTALK_PATTERNS = frozenset({
    "how are you", "как дела", "что нового", "what's up",
    "who are you", "кто ты", "what can you do", "что ты умеешь",
    "thanks", "спасибо", "thank you", "благодарю",
})


class Intent(StrEnum):
    """Classified intent for an incoming message."""

    SEARCH = "search"
    GREETING = "greeting"
    SMALLTALK = "smalltalk"
    COMMAND = "command"


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
            return self._handle_search(text, user_id, ws)
        except Exception as e:
            logger.error("router.error", intent=intent, error=str(e))
            return f"An error occurred: {e}"

    def _classify(self, text: str) -> Intent:
        """Classify the intent of a message."""
        lower = text.lower().strip()

        if lower.startswith("/"):
            return Intent.COMMAND

        if lower in _GREETING_WORDS or lower.rstrip("!") in _GREETING_WORDS:
            return Intent.GREETING

        for pattern in _SMALLTALK_PATTERNS:
            if lower.startswith(pattern):
                return Intent.SMALLTALK

        return Intent.SEARCH

    def _handle_search(self, text: str, user_id: str, workspace_id: str) -> str:
        """Handle a search query via hybrid_search_and_answer."""
        # Build composite query from conversation context
        composite = self._sessions.build_composite_query(user_id, workspace_id, text)

        logger.info("router.search", user_id=user_id, composite_len=len(composite))

        # Record user turn
        self._sessions.add_turn(user_id, workspace_id, "user", text)

        # Call existing search pipeline
        answer = hybrid_search_and_answer(
            query=text,
            user_id=user_id,
            workspace_id=workspace_id,
            intent_query=composite if composite != text else None,
        )

        # Record assistant turn
        self._sessions.add_turn(user_id, workspace_id, "assistant", answer)

        return answer

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
                    {"role": "system", "content": (
                        "You are Metatron, a helpful AI knowledge assistant for teams. "
                        "Reply briefly and friendly. Keep answers to 1-2 sentences."
                    )},
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
        """Handle slash commands."""
        parts = text.strip().split(maxsplit=1)
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

        return f"Unknown command: {command}. Type /help for available commands."

    def _cmd_help(self) -> str:
        """Return help text with available commands."""
        return (
            "**Available commands:**\n"
            "/search <query> — Search the knowledge base\n"
            "/sync [connector] — Sync data sources (confluence, jira)\n"
            "/status — Show workspace status\n"
            "/clear — Clear conversation history\n"
            "/help — Show this help message\n\n"
            "Or just type your question and I'll search for the answer."
        )

    def _cmd_sync(self, connector_type: str | None, workspace_id: str) -> str:
        """Trigger a connector sync. Blocking for MVP."""
        from metatron.connectors.registry import ConnectorRegistry, register_builtins
        from metatron.core.models import Connection
        from metatron.ingestion.pipeline import ingest_documents

        registry = ConnectorRegistry()
        register_builtins(registry)

        # If no type specified, try all configured connectors
        types_to_sync = []
        if connector_type:
            if not registry.is_registered(connector_type):
                available = registry.list_available()
                return f"Unknown connector: {connector_type}. Available: {', '.join(available)}"
            types_to_sync = [connector_type]
        else:
            # Auto-detect configured connectors from env
            settings = self._settings
            if settings.confluence_url:
                types_to_sync.append("confluence")
            if settings.jira_url:
                types_to_sync.append("jira")
            if not types_to_sync:
                return "No connectors configured. Set CONFLUENCE_URL or JIRA_URL in your environment."

        results = []
        for ct in types_to_sync:
            try:
                config = _config_from_env(ct, self._settings)
                if not config:
                    results.append(f"**{ct}**: no env config found, skipped")
                    continue

                connector = registry.create(ct)
                connection = Connection(workspace_id=workspace_id, connector_type=ct)

                # Run async connector methods from sync context
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(connector.configure(connection, config))
                    documents = loop.run_until_complete(connector.fetch(workspace_id))
                finally:
                    loop.close()

                if documents:
                    result = ingest_documents(documents, workspace_id, ct)
                    results.append(
                        f"**{ct}**: {result.documents_new} docs ingested, "
                        f"{result.documents_skipped} skipped, "
                        f"{len(result.errors)} errors"
                    )
                else:
                    results.append(f"**{ct}**: no documents found")

            except Exception as e:
                logger.error("router.sync.error", connector=ct, error=str(e))
                results.append(f"**{ct}**: error — {e}")

        return "Sync complete:\n" + "\n".join(results)

    def _cmd_status(self, workspace_id: str) -> str:
        """Show workspace status — Qdrant point count, configured connectors."""
        lines = [f"**Workspace:** {workspace_id}"]

        # Qdrant stats
        try:
            from metatron.storage.qdrant import get_hybrid_store
            store = get_hybrid_store(workspace_id)
            count = store.client.count(collection_name=store.collection_name).count
            lines.append(f"**Qdrant points:** {count}")
        except Exception as e:
            lines.append(f"**Qdrant:** unavailable ({e})")

        # Configured connectors
        configured = []
        if self._settings.confluence_url:
            configured.append("confluence")
        if self._settings.jira_url:
            configured.append("jira")
        lines.append(f"**Connectors configured:** {', '.join(configured) or 'none'}")

        # LLM provider
        lines.append(f"**LLM provider:** {self._settings.llm_provider}")
        if self._settings.llm_fallback_provider:
            lines.append(f"**LLM fallback:** {self._settings.llm_fallback_provider}")

        return "\n".join(lines)


def _config_from_env(connector_type: str, settings: Settings) -> dict[str, str]:
    """Build connector config dict from environment variables."""
    if connector_type == "confluence":
        if not settings.confluence_url:
            return {}
        return {
            "url": settings.confluence_url,
            "username": settings.confluence_username,
            "api_token": settings.confluence_api_token,
            "space_key": settings.confluence_space_key,
        }
    if connector_type == "jira":
        if not settings.jira_url:
            return {}
        return {
            "url": settings.jira_url,
            "username": settings.jira_username,
            "api_token": settings.jira_api_token,
            "project_key": settings.jira_project_key,
        }
    return {}
