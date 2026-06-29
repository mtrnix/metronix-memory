"""AgentRecord.is_system + list filtering (PROJ-372 P1)."""

from unittest.mock import AsyncMock

from metronix.agents.models import AgentRecord
from metronix.agents.service import AgentRegistryService


def test_agent_record_default_is_system_false() -> None:
    assert AgentRecord().is_system is False


async def test_list_agents_excludes_system_by_default() -> None:
    repo = AsyncMock()
    repo.list_records.return_value = []
    svc = AgentRegistryService(repo, workspace_id="WS")
    await svc.list_agents()
    kwargs = repo.list_records.await_args.kwargs
    assert kwargs["include_system"] is False


async def test_list_agents_can_include_system() -> None:
    repo = AsyncMock()
    repo.list_records.return_value = []
    svc = AgentRegistryService(repo, workspace_id="WS")
    await svc.list_agents(include_system=True)
    kwargs = repo.list_records.await_args.kwargs
    assert kwargs["include_system"] is True
