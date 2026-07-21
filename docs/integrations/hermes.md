# Hermes Integration

This compatibility page preserves the historical URL. Use the current
[Hermes Agent guide](hermes-agent.md) for supported MCP configuration,
authentication modes, verification, and the native-provider option.

**Authentication:** local `AUTH_ENABLED=false` may use the deployment MCP key;
hosted `AUTH_ENABLED=true` requires a user JWT in the Bearer header. See the
canonical guide for the exact hosted and local connection values.

For a prompt-driven migration, use the canonical templates in
[`hermes/`](hermes/). The installer fills copies with deployment values in
`metronix-hermes-setup/`; that generated directory is intentionally ignored
because it can contain credentials.
