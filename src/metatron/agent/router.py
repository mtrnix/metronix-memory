"""Message router — LLM-as-Router pattern from OpenClaw.

The router receives user messages, loads relevant skills, builds
a system prompt, calls the LLM, and executes any tool calls.
No workflow engine — the LLM decides the plan.
"""

from __future__ import annotations

import structlog

from metatron.core.interfaces import LLMProviderInterface, RetrieverInterface
from metatron.core.models import IncomingMessage, OutgoingMessage
from metatron.agent.commands import parse_command
from metatron.agent.executor import ToolExecutor
from metatron.agent.sessions import SessionStore
from metatron.agent.tools import build_tool_definitions
from metatron.skills.engine import SkillEngine

logger = structlog.get_logger()


class MessageRouter:
    """Routes incoming messages through the LLM-as-Router pipeline.

    Flow:
    1. Check for slash commands (/search, /sync, /help)
    2. Load user session history
    3. Load and select relevant skills
    4. Build system prompt with skills + tool definitions
    5. Call LLM with conversation + tools
    6. If LLM returns tool_calls → execute → feed results back → repeat
    7. Return final text response
    """

    def __init__(
        self,
        llm_provider: LLMProviderInterface,
        retriever: RetrieverInterface,
        skill_engine: SkillEngine,
        tool_executor: ToolExecutor,
        session_store: SessionStore,
    ) -> None:
        self._llm = llm_provider
        self._retriever = retriever
        self._skill_engine = skill_engine
        self._executor = tool_executor
        self._sessions = session_store

    async def route(self, message: IncomingMessage) -> OutgoingMessage:
        """Route an incoming message through the full pipeline.

        Args:
            message: Incoming message from a channel.

        Returns:
            Response to send back to the user.
        """
        logger.info(
            "router.route.started",
            channel=message.channel,
            workspace_id=message.workspace_id,
            text_length=len(message.text),
        )

        # Step 1: Check for slash commands
        command_result = await parse_command(message.text)
        if command_result is not None:
            return OutgoingMessage(
                text=command_result,
                channel=message.channel,
                channel_user_id=message.channel_user_id,
                thread_id=message.thread_id,
            )

        # TODO: implement full routing pipeline
        # Step 2: Load session history
        # history = await self._sessions.get_history(
        #     message.channel_user_id, message.workspace_id
        # )

        # Step 3: Load and select skills
        # skills = await self._skill_engine.load_skills(message.workspace_id)
        # selected = await self._skill_engine.select_skills(message.text, skills)

        # Step 4: Build system prompt
        # system_prompt = self._build_system_prompt(selected)

        # Step 5: Build messages list
        # messages = [{"role": "system", "content": system_prompt}]
        # messages.extend(history)
        # messages.append({"role": "user", "content": message.text})

        # Step 6: Call LLM with tool loop
        # tools = build_tool_definitions()
        # response = await self._llm.chat(messages, tools=tools)
        # While response has tool_calls: execute, append results, re-call

        # Step 7: Build response
        # await self._sessions.add_message(...)
        raise NotImplementedError("Message routing not yet implemented")
