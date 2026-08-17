# Authorization conformance matrix

This suite verifies that a server-derived principal receives the same
workspace-and-agent decision through REST, direct MCP invocation, and confirmed
action execution. It is intentionally content-free: tests use sentinel strings
only to prove that a denied request does not reach a storage or external-tool
boundary.

Run the focused suite with:

```bash
uv run --extra dev pytest tests/conformance tests/integration/mcp/test_agent_access_conformance.py
```

## Shared fixtures

`tests/conformance/fixtures.py` is the source of the reusable test identities
and active grants:

| Principal | Workspace | Agent | Grant | Expected access |
| --- | --- | --- | --- | --- |
| `owner` | `ws-a` | `owner-agent` | owner/admin | read and mutate |
| `delegate` | `ws-a` | `shared-agent` | delegated read | read only |
| `delegate` | `ws-a` | `shared-agent` | expired delegated write | denied |
| `delegate` | `ws-a` | `owner-agent` | none | denied |
| `delegate` | `ws-b` | any | workspace absent from principal | denied before grant lookup |

The fixtures are passed to the real `AuthorizationEvaluator`; adapters only
translate their server-derived principal and target into its normalized request.

## Matrix

| Scenario | REST | Direct MCP | Action execution | Side-effect assertion |
| --- | --- | --- | --- | --- |
| Owner accesses its agent | `tests/conformance/test_authorization_matrix.py` | same | policy unit coverage | allowed decision |
| Delegate reads explicitly shared agent | same | same | n/a | allowed decision |
| Read-only delegate attempts mutation | same | `tests/integration/mcp/test_agent_access_conformance.py` | action requires write-equivalent grant | service/client not called |
| Delegate swaps to an ungranted agent | same | `tests/integration/mcp/test_agent_access_conformance.py` | `tests/conformance/test_authorization_matrix.py` | service/client not called |
| Workspace is swapped | same | same | policy unit coverage | denied before grant lookup |
| Expired delegated grant is used | shared policy evaluator | shared policy evaluator | shared policy evaluator | `tests/integration/auth/test_agent_access_expiry.py` proves no active grant is returned |
| Hidden MCP tool is invoked directly | n/a | `tests/integration/mcp/test_agent_access_conformance.py` | n/a | tool service not built |
| Known record ID is used for update/review | route and tool tests | `tests/unit/mcp/tools/test_agent_access_guard.py` | n/a | memory service not built |
| Decision audit contains no protected content | adapter audit tests | MCP guard audit path | n/a | only policy metadata is recorded |

## Enforcement boundary

- REST calls `require_memory_access` before a route obtains its memory service.
- MCP tools call `require_agent_access` before constructing a memory service,
  including direct invocations that bypass discovery.
- `ActionExecutor` checks `EXECUTE` before loading server configuration or
  creating an `MCPClient`.

The policy evaluator treats `DELETE` and `EXECUTE` as write-equivalent agent
grants. It fails closed on a missing principal, an ungranted workspace, a
missing agent, grant-store failure, and an expired persisted grant. PostgreSQL
filters expiry with its own `now()` clock; expired rows remain auditable but do
not appear in the active-grant projection.

## Follow-up boundaries

One scenario remains deliberately outside the in-memory conformance fixtures:

1. **Full REST route integration:** the matrix invokes the REST authorization
   adapter directly so it remains hermetic. Add a Compose-backed HTTP test that
   sends a verified JWT or personal API key through the complete dependency
   chain and proves the route never constructs its storage service on denial.

These are intentionally separate from the policy matrix; they validate storage
and authentication wiring, respectively, without weakening the shared decision
contract.
