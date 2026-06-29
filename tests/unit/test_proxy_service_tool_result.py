"""ProxyService invokes enricher on tool-result rounds (PROJ-372 P4)."""

from unittest.mock import AsyncMock, MagicMock

from metronix.agents.models import AgentRecord
from metronix.core.config import Settings
from metronix.core.models import AssembledContext
from metronix.proxy.service import ProxyService
from metronix.proxy.upstream import ProxyStreamFrame


def _service(enricher: AsyncMock) -> ProxyService:
    agent_service = AsyncMock()
    agent_service.get_agent.return_value = AgentRecord(
        id="A",
        workspace_id="WS",
        name="a",
        capabilities=[],
        current_config={"upstream": {"provider": "openai", "model_name": "m"}},
    )
    assembler = AsyncMock()
    assembler.assemble.return_value = AssembledContext(
        system_prompt="<relevant_memories>\n- x\n</relevant_memories>",
        sections={
            "constitution": "",
            "preferences": "",
            "relevant_memories": "- x",
            "relevant_knowledge": "",
        },
        correlation_id="c",
    )

    async def _stream(**kwargs):
        yield ProxyStreamFrame(raw=b"data: [DONE]\n\n", status=200)

    upstream = MagicMock()
    upstream.stream = _stream
    creds = AsyncMock()
    creds.resolve.return_value = "k"
    return ProxyService(
        assembler=assembler,
        upstream_client=upstream,
        credentials=creds,
        agent_service=agent_service,
        event_bus=AsyncMock(),
        settings=Settings(),
        activity_logger_factory=lambda ws: AsyncMock(),
        tool_result_enricher_factory=lambda ws: enricher,
    )


async def test_tool_result_round_calls_enricher() -> None:
    enricher = AsyncMock()
    svc = _service(enricher)
    resp = await svc.dispatch(
        agent_id="A",
        workspace_id="WS",
        request_body={
            "model": "m",
            "stream": True,
            "messages": [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "t"}]},
                {"role": "tool", "content": "Acme shipped widgets"},
            ],
        },
        mode="proxy",
    )
    _ = b"".join([c async for c in resp.body_iterator])
    enricher.enrich.assert_awaited_once()


async def test_non_tool_round_skips_enricher() -> None:
    enricher = AsyncMock()
    svc = _service(enricher)
    resp = await svc.dispatch(
        agent_id="A",
        workspace_id="WS",
        request_body={
            "model": "m",
            "stream": True,
            "messages": [{"role": "user", "content": "q"}],
        },
        mode="proxy",
    )
    _ = b"".join([c async for c in resp.body_iterator])
    enricher.enrich.assert_not_called()
