"""Tool executor — sandboxed execution of LLM tool calls.

Enforces domain allowlists for HTTP requests and command allowlists
for shell execution. All tool calls are logged via structlog.
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlparse

import httpx
import structlog

from metatron.core.exceptions import SecurityError, ToolDisabledError, ToolTimeoutError

logger = structlog.get_logger()

DEFAULT_HTTP_TIMEOUT = 30.0
DEFAULT_COMMAND_TIMEOUT = 10.0


class ToolExecutor:
    """Executes LLM tool calls with security sandboxing.

    Two tools:
    - http_request: HTTP calls restricted to domain allowlist
    - exec_command: Shell commands restricted to command allowlist

    Both enforce timeouts and log all invocations.
    """

    def __init__(
        self,
        allowed_domains: list[str] | None = None,
        allowed_commands: list[str] | None = None,
        http_timeout: float = DEFAULT_HTTP_TIMEOUT,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
    ) -> None:
        self._allowed_domains = set(allowed_domains or [])
        self._allowed_commands = set(allowed_commands or [])
        self._http_timeout = http_timeout
        self._command_timeout = command_timeout
        self._http_client = httpx.AsyncClient(timeout=http_timeout)

    async def execute(
        self, tool_name: str, arguments: dict[str, object]
    ) -> str:
        """Execute a tool call and return the result as a string.

        Args:
            tool_name: The tool to execute (http_request, exec_command, etc.).
            arguments: Tool-specific arguments dict.

        Returns:
            String result for feeding back to the LLM.

        Raises:
            ToolDisabledError: If the tool is not recognized.
            SecurityError: If the call violates security policy.
            ToolTimeoutError: If execution exceeds timeout.
        """
        logger.info("executor.execute", tool=tool_name, arguments=arguments)

        if tool_name == "http_request":
            return await self._http_request(arguments)
        elif tool_name == "exec_command":
            return await self._exec_command(arguments)
        elif tool_name == "knowledge_search":
            return await self._knowledge_search(arguments)
        else:
            raise ToolDisabledError(f"Unknown tool: {tool_name}")

    async def _http_request(self, args: dict[str, object]) -> str:
        """Execute an HTTP request with domain allowlist enforcement.

        Args:
            args: Must contain "method" and "url". Optional: "params", "body".

        Returns:
            Response body as string (truncated to 4000 chars for LLM context).

        Raises:
            SecurityError: If domain not in allowlist.
            ToolTimeoutError: If request times out.
        """
        method = str(args.get("method", "GET")).upper()
        url = str(args.get("url", ""))
        params = args.get("params")
        body = args.get("body")

        # Domain allowlist check
        parsed = urlparse(url)
        domain = parsed.hostname or ""
        if self._allowed_domains and domain not in self._allowed_domains:
            raise SecurityError(
                f"Domain '{domain}' not in allowlist. "
                f"Allowed: {sorted(self._allowed_domains)}"
            )

        logger.info("executor.http_request", method=method, url=url, domain=domain)

        try:
            response = await self._http_client.request(
                method=method,
                url=url,
                params=params,  # type: ignore[arg-type]
                json=body if body else None,
            )
            text = response.text[:4000]
            logger.info(
                "executor.http_request.done",
                status_code=response.status_code,
                body_length=len(response.text),
            )
            return f"HTTP {response.status_code}\n{text}"
        except httpx.TimeoutException:
            raise ToolTimeoutError(f"HTTP request to {url} timed out")

    async def _exec_command(self, args: dict[str, object]) -> str:
        """Execute a shell command with allowlist enforcement.

        Args:
            args: Must contain "command". Optional: "args" (list of strings).

        Returns:
            Command stdout (truncated to 2000 chars).

        Raises:
            SecurityError: If command not in allowlist.
            ToolTimeoutError: If execution exceeds timeout.
        """
        command = str(args.get("command", ""))
        cmd_args = [str(a) for a in args.get("args", [])]  # type: ignore[union-attr]

        if self._allowed_commands and command not in self._allowed_commands:
            raise SecurityError(
                f"Command '{command}' not in allowlist. "
                f"Allowed: {sorted(self._allowed_commands)}"
            )

        full_cmd = [command, *cmd_args]
        logger.info("executor.exec_command", command=full_cmd)

        try:
            process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self._command_timeout
            )
            output = stdout.decode()[:2000]
            if process.returncode != 0:
                err = stderr.decode()[:500]
                output += f"\nSTDERR: {err}\nExit code: {process.returncode}"
            logger.info(
                "executor.exec_command.done",
                returncode=process.returncode,
                output_length=len(output),
            )
            return output
        except asyncio.TimeoutError:
            raise ToolTimeoutError(
                f"Command '{command}' exceeded {self._command_timeout}s timeout"
            )

    async def _knowledge_search(self, args: dict[str, object]) -> str:
        """Placeholder for knowledge search tool.

        In production, this calls the retriever. For now returns a stub.
        """
        query = str(args.get("query", ""))
        workspace_id = str(args.get("workspace_id", ""))
        logger.info(
            "executor.knowledge_search",
            query=query,
            workspace_id=workspace_id,
        )
        # TODO: implement via self._retriever.retrieve()
        # This requires the retriever to be injected into the executor
        return json.dumps({"status": "not_implemented", "query": query})

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http_client.aclose()
