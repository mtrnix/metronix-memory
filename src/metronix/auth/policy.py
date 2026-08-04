"""Transport-neutral, fail-closed authorization decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

if TYPE_CHECKING:
    from metronix.core.models import User
    from metronix.mcp.principal import MCPPrincipal


class Capability(StrEnum):
    """Capabilities requested for a protected resource."""

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
    ADMINISTER = "administer"


class ResourceType(StrEnum):
    """Resource families covered by the policy contract."""

    MEMORY = "memory"
    ACTION = "action"


class Transport(StrEnum):
    """Transport that submitted the authorization request."""

    REST = "rest"
    MCP = "mcp"
    ACTION = "action"


@dataclass(frozen=True)
class PolicyPrincipal:
    """Server-derived identity consumed by every policy adapter."""

    user_id: str
    role: str
    workspace_ids: tuple[str, ...]
    auth_method: str

    @classmethod
    def from_mcp(cls, principal: MCPPrincipal) -> PolicyPrincipal:
        return cls(
            user_id=principal.user_id,
            role=principal.role,
            workspace_ids=principal.workspace_ids,
            auth_method=principal.auth_method,
        )

    @classmethod
    def from_user(cls, user: User) -> PolicyPrincipal:
        return cls(
            user_id=user.id,
            role=str(user.role),
            workspace_ids=tuple(user.workspace_ids),
            auth_method="user",
        )


@dataclass(frozen=True)
class AuthorizationRequest:
    """Normalized request whose target values do not confer authority."""

    principal: PolicyPrincipal | None
    workspace_id: str
    agent_id: str | None
    resource_type: ResourceType
    capability: Capability
    transport: Transport
    resource_id: str | None = None


@dataclass(frozen=True)
class AuthorizationDecision:
    """Content-free authorization result suitable for audit logging."""

    decision_id: str
    allowed: bool
    reason: str
    policy_version: str = "authz-v1"


class AgentAccessGrantLike(Protocol):
    """Active agent grant projection used by the evaluator."""

    capability: str
    grant_type: str


class AgentAccessStore(Protocol):
    """Lookup boundary for server-authoritative active agent grants."""

    async def list_active_grants(
        self, workspace_id: str, agent_id: str, principal_user_id: str
    ) -> list[AgentAccessGrantLike]:
        """Return grants for exactly one principal and agent target."""


class AuthorizationEvaluator:
    """Evaluate agent-memory access without trusting transport request scope."""

    def __init__(self, agent_access_store: AgentAccessStore) -> None:
        self._agent_access_store = agent_access_store

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationDecision:
        principal = request.principal
        if principal is None:
            return self._decision(False, "principal_required")
        if (
            request.workspace_id not in principal.workspace_ids
            and "*" not in principal.workspace_ids
        ):
            return self._decision(False, "workspace_not_granted")
        if request.resource_type not in (ResourceType.MEMORY, ResourceType.ACTION):
            return self._decision(False, "unsupported_resource")
        if not request.agent_id:
            return self._decision(False, "agent_id_required")
        if principal.role == "admin":
            return self._decision(True, "admin_override")

        try:
            grants = await self._agent_access_store.list_active_grants(
                request.workspace_id, request.agent_id, principal.user_id
            )
        except Exception:  # noqa: BLE001 - authorization must fail closed
            return self._decision(False, "grant_lookup_failed")

        requested_grant = self._required_agent_capability(request.capability)
        if requested_grant is None:
            return self._decision(False, "capability_not_supported")
        allowed_grants = [
            grant for grant in grants if self._covers(grant.capability, requested_grant)
        ]
        if not allowed_grants:
            return self._decision(
                False, "no_active_grant" if not grants else "capability_not_granted"
            )
        if any(grant.grant_type == "owner" for grant in allowed_grants):
            return self._decision(True, "owner_grant")
        return self._decision(True, "delegated_grant")

    @staticmethod
    def _required_agent_capability(capability: Capability) -> Capability | None:
        if capability is Capability.DELETE:
            return Capability.WRITE
        if capability is Capability.EXECUTE:
            return Capability.WRITE
        if capability is Capability.ADMINISTER:
            return Capability.ADMINISTER
        if capability in (Capability.READ, Capability.WRITE):
            return capability
        return None

    @staticmethod
    def _covers(granted: str, requested: Capability) -> bool:
        levels = {Capability.READ: 1, Capability.WRITE: 2, Capability.ADMINISTER: 3}
        try:
            normalized_granted = (
                Capability.ADMINISTER if granted == "admin" else Capability(granted)
            )
            return levels[normalized_granted] >= levels[requested]
        except ValueError:
            return False

    @staticmethod
    def _decision(allowed: bool, reason: str) -> AuthorizationDecision:
        return AuthorizationDecision(decision_id=uuid4().hex, allowed=allowed, reason=reason)
