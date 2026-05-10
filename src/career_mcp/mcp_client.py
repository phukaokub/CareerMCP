"""MCP client wrapper.

Provides a high-level async interface for connecting to multiple MCP
servers (LinkedIn, JobsDB, …) defined in mcp_servers.yaml and
exposes their combined toolsets to the AI agent.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.types import Tool

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    """Raised when an MCP server operation fails."""


class MCPServerConnection:
    """Manages a single MCP server connection (stdio or SSE)."""

    def __init__(self, name: str, config: dict) -> None:
        self.name = name
        self._config = config
        self._session: ClientSession | None = None
        self._tools: list[Tool] = []

    @property
    def tools(self) -> list[Tool]:
        return self._tools

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator["MCPServerConnection", None]:
        transport = self._config.get("transport", "stdio")
        try:
            if transport == "stdio":
                async with self._connect_stdio() as session:
                    self._session = session
                    await self._load_tools()
                    yield self
            elif transport == "sse":
                async with self._connect_sse() as session:
                    self._session = session
                    await self._load_tools()
                    yield self
            else:
                raise MCPClientError(f"Unknown transport '{transport}' for server '{self.name}'")
        finally:
            self._session = None
            self._tools = []

    @asynccontextmanager
    async def _connect_stdio(self) -> AsyncGenerator[ClientSession, None]:
        params = StdioServerParameters(
            command=self._config["command"],
            args=self._config.get("args", []),
            env=self._config.get("env"),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    @asynccontextmanager
    async def _connect_sse(self) -> AsyncGenerator[ClientSession, None]:
        url = self._config["url"]
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def _load_tools(self) -> None:
        if self._session is None:
            return
        response = await self._session.list_tools()
        self._tools = response.tools
        logger.info(
            "Server '%s' exposes %d tools: %s",
            self.name,
            len(self._tools),
            [t.name for t in self._tools],
        )

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the connected MCP server."""
        if self._session is None:
            raise MCPClientError(f"Server '{self.name}' is not connected.")
        try:
            result = await self._session.call_tool(tool_name, arguments)
            return result
        except Exception as exc:
            raise MCPClientError(
                f"Tool '{tool_name}' on server '{self.name}' failed: {exc}"
            ) from exc


class MCPClientPool:
    """Manages connections to all configured MCP servers simultaneously."""

    def __init__(self, server_configs: dict[str, dict]) -> None:
        self._configs = server_configs
        self._connections: dict[str, MCPServerConnection] = {}

    @property
    def connections(self) -> dict[str, MCPServerConnection]:
        return self._connections

    def all_tools(self) -> list[dict]:
        """Return all tools from all servers in Anthropic tool-call format."""
        tools = []
        for server_name, conn in self._connections.items():
            for tool in conn.tools:
                tools.append(
                    {
                        "name": f"{server_name}__{tool.name}",
                        "description": (
                            f"[{server_name}] {tool.description or tool.name}"
                        ),
                        "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
                    }
                )
        return tools

    async def call_tool(self, namespaced_name: str, arguments: dict[str, Any]) -> Any:
        """Call a namespaced tool (e.g. 'linkedin__search_jobs')."""
        if "__" not in namespaced_name:
            raise MCPClientError(
                f"Tool name '{namespaced_name}' is not namespaced. "
                "Expected format: '<server_name>__<tool_name>'"
            )
        server_name, tool_name = namespaced_name.split("__", 1)
        conn = self._connections.get(server_name)
        if conn is None:
            raise MCPClientError(f"No connection for server '{server_name}'")
        return await conn.call_tool(tool_name, arguments)

    @asynccontextmanager
    async def connect_all(self) -> AsyncGenerator["MCPClientPool", None]:
        """Connect to all servers concurrently and yield this pool."""
        # We open each server in a nested context manager stack
        stack: list[Any] = []
        cms = [
            MCPServerConnection(name, cfg).connect()
            for name, cfg in self._configs.items()
        ]

        async def _enter_all():
            for i, (name, _cfg) in enumerate(self._configs.items()):
                conn_cm = cms[i]
                conn = await conn_cm.__aenter__()
                self._connections[name] = conn
                stack.append((conn_cm, conn))

        async def _exit_all(exc_type, exc, tb):
            for conn_cm, _conn in reversed(stack):
                await conn_cm.__aexit__(exc_type, exc, tb)

        try:
            await _enter_all()
            yield self
        except Exception:
            raise
        finally:
            await _exit_all(None, None, None)
            self._connections.clear()
