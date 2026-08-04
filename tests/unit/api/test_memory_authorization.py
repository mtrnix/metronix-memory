"""REST memory authorization adapter coverage."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from metronix.core.models import Role, User


@pytest.mark.asyncio
async def test_rest_adapter_denies_before_memory_service_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metronix.api.routes import memory
    from metronix.auth.policy import AuthorizationDecision

    class DenyingEvaluator:
        request = None

        async def authorize(self, request):
            self.request = request
            return AuthorizationDecision("decision-1", False, "no_active_grant")

    evaluator = DenyingEvaluator()
    monkeypatch.setattr(memory, "get_authorization_evaluator", lambda: evaluator)
    user = User(id="user-1", role=Role.EDITOR, workspace_ids=["workspace-1"])

    with pytest.raises(HTTPException) as exc_info:
        await memory.require_memory_access(user, "workspace-1", "agent-1", "read")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "code": "memory_access_denied",
        "reason": "no_active_grant",
        "decision_id": "decision-1",
    }
    assert evaluator.request.workspace_id == "workspace-1"
    assert evaluator.request.agent_id == "agent-1"
    assert evaluator.request.transport == "rest"
