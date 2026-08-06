# MCP JWT principals and workspace grants

## Goal

Implement issue #312 by making MCP authenticate the same concrete JWT user
principal as REST. The result is trusted, server-derived identity and workspace
grant context that issue #314 can later authorize against.

## Scope

The implementation accepts JWT bearer credentials for MCP in production and
exposes a typed request-scoped principal containing the authenticated user ID,
role, workspace grants, and `auth_method="jwt"`.

It does not add service/API-key principals, resource policy decisions, agent
delegation rules, or cross-transport authorization conformance. Those remain
separate work for issues #314 and #310.

## Authentication and context

1. Define an immutable `MCPPrincipal` value with `user_id`, `role`,
   `workspace_ids`, and `auth_method` fields.
2. Define a context variable with bind/get/reset helpers so MCP dispatch and
   tools can retrieve the current principal without accepting client-provided
   identity fields.
3. In production (`AUTH_ENABLED=true`), MCP HTTP middleware requires a bearer
   JWT and validates it through the existing JWT verifier and configured secret.
   Invalid, missing, or expired credentials receive a 401 response.
4. Admin JWTs with an empty workspace list are normalized to `["*"]`, matching
   REST. Every other empty list grants access to no workspaces.
5. The deployment-wide `METRONIX_MCP_API_KEY` is not a hosted-user identity and
   is rejected on production MCP requests. With authentication disabled, the
   local development flow retains its existing trusted-admin behavior.

## Workspace resolution

MCP workspace resolution consumes the bound principal rather than treating a
tool argument as authority.

- A requested workspace must be syntactically valid and present in the
  principal's grants, unless the principal carries `["*"]`.
- An omitted workspace selects the principal's first concrete workspace. A
  wildcard principal falls back to the configured default workspace.
- A principal without a usable grant fails closed before any store or registry
  lookup.
- `X-Agent-Id` remains validated request context only. It neither grants
  ownership nor delegation; the future shared evaluator receives it alongside
  the principal.

## Migration and documentation

MCP clients in hosted deployments change from
`Authorization: Bearer $METRONIX_MCP_API_KEY` to a user JWT bearer token.
Documentation will describe that the shared MCP key is development-only, plus
the expected 401 authentication and 403 workspace-grant failure behavior.

## Verification

Tests will prove:

1. Valid and invalid JWTs resolve or reject an `MCPPrincipal` correctly.
2. Empty-grant and admin-wildcard behavior matches REST.
3. Production MCP rejects the shared deployment key and accepts a valid JWT.
4. Granted workspaces resolve; ungranted or malformed values fail before store
   construction.
5. The same JWT produces equal effective workspace grants for REST and MCP.

## Non-goals and follow-up boundaries

This slice deliberately establishes authentication and authoritative request
context only. Issue #314 will use the principal, resource, operation, and
agent-context inputs to make auditable allow/deny decisions at discovery and
execution boundaries. Issue #310 will verify the transport-neutral policy
contract.
