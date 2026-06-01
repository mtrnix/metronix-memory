"""GET /api/v1/agents?include_system query param (MTRNIX-372 P1)."""

from unittest.mock import AsyncMock

from metatron.agents.service import AgentRegistryService


async def test_list_agents_passes_include_system_true() -> None:
    repo = AsyncMock()
    repo.list_records.return_value = []
    svc = AgentRegistryService(repo, workspace_id="WS")
    await svc.list_agents(include_system=True, limit=51, offset=0)
    assert repo.list_records.await_args.kwargs["include_system"] is True
