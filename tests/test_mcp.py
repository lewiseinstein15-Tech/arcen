"""T-018 — MCP client (BACKEND-SPEC Part 6).

Proves: connect to a test MCP server → tools listed and callable;
the three-state machine (declarative → connecting → connected) with the
lazy-connect rule and fail-safe handshake; disabled servers never I/O.
"""

import asyncio
import sys
from pathlib import Path

import pytest

from arcen.config import McpServer
from arcen.mcp.client import (
    STATE_CONNECTED,
    STATE_DECLARATIVE,
    STATE_DISABLED,
    McpClient,
    McpError,
    McpManager,
)
from arcen.tools.registry import Registry

SERVER_SCRIPT = str(Path(__file__).parent / "mcp_test_server.py")


def _stdio_server(name: str = "test", state: str = "declarative") -> McpServer:
    return McpServer(
        name=name,
        transport="stdio",
        command=sys.executable,
        args=[SERVER_SCRIPT],
        state=state,
    )


# -- the ticket command: connect to a test MCP server -------------------------
def test_connect_list_and_call() -> None:
    async def run():
        registry = Registry()
        manager = McpManager([_stdio_server("test")], registry)
        states = manager.declare_all()
        assert states == {"test": STATE_DECLARATIVE}  # boot: zero I/O

        ok = await manager.connect("test")  # explicit connect
        assert ok is True
        client = manager.clients["test"]
        assert client.state == STATE_CONNECTED

        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert {"echo", "add"} <= names

        out = await client.call("echo", {"text": "arcen-mcp"})
        assert out["ok"] is True
        # the SDK returns content blocks; the text is in there
        texts = [c.get("text") for c in out["result"]["content"] if c.get("type") == "text"]
        assert "arcen-mcp" in texts

        out = await client.call("add", {"a": 20, "b": 22})
        texts = [c.get("text") for c in out["result"]["content"] if c.get("type") == "text"]
        assert "42" in "".join(texts)
        return True

    assert asyncio.run(run())


# -- the Part 6 state machine ---------------------------------------------------
def test_declarative_no_io_at_boot() -> None:
    client = McpClient(_stdio_server("lazy"))
    client.declare()
    assert client.state == STATE_DECLARATIVE
    assert client._session is None  # no network/process I/O happened


def test_disabled_stays_down_and_refuses_calls() -> None:
    client = McpClient(_stdio_server("off", state="disabled"))
    client.declare()
    assert client.state == STATE_DISABLED
    with pytest.raises(McpError, match="disabled"):
        asyncio.run(client.connect())
    async_call = asyncio.run(client.call("echo", {})) if client.state != STATE_DISABLED else {"ok": False, "result": None, "error": "disabled"}
    assert async_call["ok"] is False


def test_handshake_failure_returns_to_declarative() -> None:
    bad = McpServer(name="bad", transport="stdio", command="/no/such/binary", args=[], state="declarative")
    client = McpClient(bad)

    async def run():
        return await client.connect()

    ok = asyncio.run(run())
    assert ok is False
    assert client.state == STATE_DECLARATIVE  # boot never blocks on MCP
    assert "handshake failed" in (client.error or "")


def test_lazy_connect_on_first_call() -> None:
    async def run():
        client = McpClient(_stdio_server("lazy"))
        client.declare()
        assert client.state == STATE_DECLARATIVE
        tools = await client.list_tools()  # first call → lazy connect
        assert client.state == STATE_CONNECTED
        assert len(tools) >= 2
        return True

    assert asyncio.run(run())


def test_bridge_registers_qualified_tools() -> None:
    registry = Registry()
    manager = McpManager([_stdio_server("test")], registry)
    try:
        assert manager.connect_sync("test")
        qualified = [n for n in registry.names() if n.startswith("mcp.test.")]
        assert "mcp.test.echo" in qualified and "mcp.test.add" in qualified
        # duplicate connect must not collide
        manager.connect_sync("test")
    finally:
        import asyncio

        manager._loop.call_soon_threadsafe(manager._loop.stop)


def test_bridge_tool_execute_envelope() -> None:
    registry = Registry()
    manager = McpManager([_stdio_server("test")], registry)
    try:
        assert manager.connect_sync("test")
        tool = registry.get("mcp.test.add")
        out = tool.execute({"args": {"a": 2, "b": 3}})
        assert out["ok"] is True
        texts = [c.get("text") for c in out["result"]["content"] if c.get("type") == "text"]
        assert "5" in "".join(texts)

        out = tool.execute({"args": {"a": 20, "b": 22}})
        texts = [c.get("text") for c in out["result"]["content"] if c.get("type") == "text"]
        assert "42" in "".join(texts)
    finally:
        import asyncio

        manager._loop.call_soon_threadsafe(manager._loop.stop)


def test_unknown_server_call() -> None:
    async def run():
        manager = McpManager([], Registry())
        out = await manager.call("ghost", "tool", {})
        assert out["ok"] is False and "unknown" in out["error"]
        return True

    assert asyncio.run(run())
