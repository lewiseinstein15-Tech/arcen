"""ARCEN — MCP client (BACKEND-SPEC Part 2 row 8 / Part 6).

Pulled from the MCP Python SDK (client/) — stdio + HTTP transports,
initialize handshake, tools/list, tools/call.

Edited per the Pull Map: the lazy three-state machine (Part 6). Each
configured server is always in exactly one state:

    declarative ── first call / explicit connect ──▶ connecting
    connecting   ── handshake ok ──▶ connected ──▶ disabled (via config)
    connecting   ── handshake fail ──▶ back to declarative + error event

Lazy connection rule: no MCP network I/O at boot — ever. ``declare_all``
lists servers and applies ``disabled``; a ``declarative`` server
connects on its first tool call. Boot never blocks on MCP.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from arcen.config import McpServer
from arcen.tools.registry import Registry


class McpError(RuntimeError):
    pass


STATE_DECLARATIVE = "declarative"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_DISABLED = "disabled"


@dataclass
class McpToolRef:
    """A tool advertised by a remote MCP server."""

    server: str
    name: str  # remote name
    qualified: str  # "mcp.<server>.<name>"
    description: str


class McpClient:
    """One configured MCP server. Owns its state machine + transport."""

    def __init__(self, config: McpServer) -> None:
        self.config = config
        self.name = config.name
        self.state: str = STATE_DECLARATIVE
        self.error: str | None = None
        self.tools: list[McpToolRef] = []
        self._session: Any = None
        self._stack: Any = None
        self._lock = asyncio.Lock()

    # -- boot ------------------------------------------------------------------
    def declare(self) -> None:
        """Apply the boot state machine. Zero network I/O."""
        self.state = STATE_DISABLED if self.config.state == "disabled" else STATE_DECLARATIVE

    def disable(self) -> None:
        self.state = STATE_DISABLED
        self.tools = []

    # -- the lazy connect -------------------------------------------------------
    async def connect(self) -> bool:
        """Handshake now. Fail → back to declarative with the error kept."""
        if self.state == STATE_DISABLED:
            raise McpError(f"mcp {self.name!r} is disabled")
        if self.state == STATE_CONNECTED:
            return True
        self.state = STATE_CONNECTING
        try:
            self._session = await self._open_session()
            listing = await self._session.list_tools()
            self.tools = [
                McpToolRef(
                    server=self.name,
                    name=t.name,
                    qualified=f"mcp.{self.name}.{t.name}",
                    description=t.description or "",
                )
                for t in listing.tools
            ]
            self.state = STATE_CONNECTED
            self.error = None
            return True
        except Exception as exc:  # noqa: BLE001 — handshake failure is a state, not a crash
            self._session = None
            self.tools = []
            self.state = STATE_DECLARATIVE  # boot never blocks on MCP (Part 6)
            self.error = f"handshake failed: {exc}"
            return False

    async def ensure_connected(self) -> bool:
        """First tool call triggers the lazy connect."""
        async with self._lock:
            if self.state == STATE_CONNECTED:
                return True
            return await self.connect()

    # -- tool surface ---------------------------------------------------------------
    async def list_tools(self) -> list[McpToolRef]:
        await self.ensure_connected()
        return self.tools

    async def call(self, tool: str, args: dict) -> dict:
        """Call a remote tool. Returns the frozen envelope."""
        ok = await self.ensure_connected()
        if not ok:
            return {"ok": False, "result": None, "error": self.error}
        try:
            result = await self._session.call_tool(tool, args)
            payload = {"content": [c.model_dump() for c in result.content]}
            if getattr(result, "structuredContent", None) is not None:
                payload["structured"] = result.structuredContent
            if getattr(result, "isError", False):
                return {"ok": False, "result": payload, "error": "tool reported error"}
            return {"ok": True, "result": payload, "error": None}
        except Exception as exc:  # noqa: BLE001 — envelope contract
            return {"ok": False, "result": None, "error": str(exc)}

    # -- transports (MCP Python SDK) ----------------------------------------------
    async def _open_session(self) -> Any:
        from contextlib import AsyncExitStack

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = AsyncExitStack()
        try:
            if self.config.transport == "stdio":
                params = StdioServerParameters(
                    command=self.config.command or "npx",
                    args=list(self.config.args or []),
                    env=None,
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif self.config.transport == "http":
                from mcp.client.streamable_http import streamablehttp_client

                if not self.config.url:
                    raise McpError("http transport requires url")
                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(
                        self.config.url,
                        headers={k: v for k, v in (self.config.headers or {}).items()},
                    )
                )
            else:
                raise McpError(f"unknown transport {self.config.transport!r}")
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._stack = stack  # kept open for the process lifetime
            return session
        except Exception:
            await stack.aclose()
            raise


class McpManager:
    """All configured servers. Boot declares; calls connect lazily.

    MCP sessions are bound to the event loop that created them, so the
    manager owns a dedicated background loop. Sync callers (FORGE, the
    tool registry) go through ``connect_sync`` / ``call_sync``, which
    hop onto that loop; async callers use the coroutine API on their own.
    """

    def __init__(self, configs: list[McpServer], registry: Registry) -> None:
        import threading

        self.clients: dict[str, McpClient] = {}
        self.registry = registry
        for cfg in configs:
            client = McpClient(cfg)
            client.declare()
            self.clients[cfg.name] = client
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="arcen-mcp")
        self._thread.start()

    def _submit(self, coro, timeout: float = 60.0):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    def connect_sync(self, name: str) -> bool:
        return self._submit(self.connect(name))

    def call_sync(self, server: str, tool: str, args: dict) -> dict:
        return self._submit(self.call(server, tool, args))

    def declare_all(self) -> dict[str, str]:
        """Boot step 7 — zero network I/O."""
        return {name: c.state for name, c in self.clients.items()}

    async def connect(self, name: str) -> bool:
        client = self.clients.get(name)
        if client is None:
            raise McpError(f"unknown mcp server {name!r}")
        ok = await client.connect()
        if ok:
            self.bridge(name, client)
        return ok

    def bridge(self, name: str, client: McpClient) -> None:
        """Expose remote tools in the registry as mcp.<server>.<tool>."""
        from arcen.mcp.bridge import McpBridgeTool

        for ref in client.tools:
            if ref.qualified not in self.registry:
                self.registry.register(McpBridgeTool(self, client, ref))

    async def call(self, server: str, tool: str, args: dict) -> dict:
        client = self.clients.get(server)
        if client is None:
            return {"ok": False, "result": None, "error": f"unknown mcp server {server!r}"}
        if client.state == STATE_DISABLED:
            return {"ok": False, "result": None, "error": f"mcp {server!r} is disabled"}
        return await client.call(tool, args)

    async def shutdown(self) -> None:  # pragma: no cover — teardown
        for client in self.clients.values():
            stack = getattr(client, "_stack", None)
            if stack is not None:
                try:
                    await stack.aclose()
                except Exception:  # noqa: BLE001
                    pass
                client._stack = None
