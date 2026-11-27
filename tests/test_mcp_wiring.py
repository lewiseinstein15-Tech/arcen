"""MCP servers reach the model, not just the client class.

``McpManager`` could connect, list and call since it was written, and nothing
ever constructed it: no server was declared at boot, no tool was bridged, and
the planner could not name a remote tool. These tests drive the real stdio
test server through the server's own wiring — boot declaration, background
connect, bridge registration, catalog visibility, and the HTTP surface.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import arcen.server.app as server_app
from arcen.config import ArcenConfig, McpServer
from arcen.mcp.bridge import McpBridgeTool
from arcen.mcp.client import (
    STATE_DECLARATIVE,
    STATE_DISABLED,
    McpClient,
    McpError,
    McpToolRef,
)
from arcen.server.app import ServerState, app
from arcen.tools import catalog
from arcen.tools.mcp_tools import McpListTool

SERVER_SCRIPT = str(Path(__file__).parent / "mcp_test_server.py")


def _needs_sdk():
    return pytest.importorskip(
        "mcp", reason="MCP Python SDK not installed — pip install 'arcen[mcp]'"
    )


def _config(**kwargs) -> ArcenConfig:
    cfg = ArcenConfig(**kwargs)
    return cfg


def _server(name: str = "test", state: str = "declarative") -> McpServer:
    return McpServer(
        name=name, transport="stdio", command=sys.executable, args=[SERVER_SCRIPT], state=state
    )


@pytest.fixture()
def state(tmp_path):
    cfg = _config(mcps=[_server("test")])
    cfg.session.dir = str(tmp_path)
    cfg_path = tmp_path / "config.yaml"
    st = ServerState(config=cfg)
    st.config_path = cfg_path
    yield st
    st.mcp._loop.call_soon_threadsafe(st.mcp._loop.stop)


def _wait_for(predicate, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_boot_declares_without_connecting(state):
    """Boot must not block on MCP: declaration only, connection in the background."""
    assert state.mcp.clients["test"].state in {STATE_DECLARATIVE, "connecting", "connected"}
    assert state.mcp_thread is not None


def test_background_connect_bridges_tools_into_the_catalog(state):
    _needs_sdk()
    assert _wait_for(lambda: state.mcp.clients["test"].state == "connected")
    names = state.host_registry.names()
    assert {"mcp.test.echo", "mcp.test.add"} <= set(names)

    brief = catalog.render_many(
        (state.registry, state.host_registry),
        available=server_app._plannable_tools(state),
    )
    assert "mcp.test.add" in brief
    # The remote schema travels with the tool, so the model sees real arguments.
    assert "a" in brief


def test_bridged_tool_runs_through_the_composite(state):
    _needs_sdk()
    from arcen.tools.composite import CompositeRegistry

    assert _wait_for(lambda: state.mcp.clients["test"].state == "connected")
    composite = CompositeRegistry(_FakeSandbox(), state.host_registry)
    out = composite.dispatch("mcp.test.add", {"a": 20, "b": 22})
    assert out["ok"] is True
    texts = "".join(c.get("text", "") for c in out["result"]["content"])
    assert "42" in texts


class _FakeSandbox:
    def available_tools(self):
        return ["bash"]

    def dispatch(self, name, args):
        return {"ok": True, "result": {"ran": "sandbox"}, "error": None}


def test_disabled_server_is_declared_and_never_connects():
    cfg = _config(mcps=[_server("off", state="disabled")])
    st = ServerState(config=cfg)
    try:
        assert st.mcp.clients["off"].state == STATE_DISABLED
        with pytest.raises(McpError):  # a disabled server is refused, not retried
            st.mcp.connect_sync("off")
        assert not [n for n in st.host_registry.names() if n.startswith("mcp.off.")]
    finally:
        st.mcp._loop.call_soon_threadsafe(st.mcp._loop.stop)


def test_server_list_reports_state_and_tools(state):
    _needs_sdk()
    assert _wait_for(lambda: state.mcp.clients["test"].state == "connected")
    out = McpListTool(state.mcp).execute({})
    assert out["ok"] is True
    server = out["result"]["servers"][0]
    assert server["name"] == "test" and server["state"] == "connected"
    assert "mcp.test.echo" in server["tools"]


def test_api_reports_servers_and_connects_on_demand(monkeypatch, tmp_path):
    _needs_sdk()
    cfg = _config(mcps=[_server("api")])
    cfg.session.dir = str(tmp_path)
    st = ServerState(config=cfg)
    st.config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(server_app, "STATE", st)
    try:
        body = TestClient(app).get("/api/mcp").json()
        assert body["count"] == 1 and body["servers"][0]["name"] == "api"

        connected = TestClient(app).post("/api/mcp/api/connect").json()
        assert connected["ok"] is True
        assert "mcp.api.echo" in connected["tools"]
        assert TestClient(app).post("/api/mcp/ghost/connect").status_code == 404
    finally:
        st.mcp._loop.call_soon_threadsafe(st.mcp._loop.stop)


# -- schema and argument shapes ---------------------------------------------


class _StubManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def call_sync(self, server, tool, args):
        self.calls.append((server, tool, args))
        return {"ok": True, "result": {"content": []}, "error": None}


def test_bridge_advertises_the_remote_schema():
    ref = McpToolRef(
        server="s",
        name="search",
        qualified="mcp.s.search",
        description="remote search",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    tool = McpBridgeTool(_StubManager(), McpClient(_server("s")), ref)
    assert tool.schema()["required"] == ["query"]


def test_bridge_passes_arguments_in_either_shape():
    manager = _StubManager()
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    ref = McpToolRef("s", "search", "mcp.s.search", "remote", input_schema=schema)
    tool = McpBridgeTool(manager, McpClient(_server("s")), ref)
    tool.execute({"query": "a"})
    tool.execute({"args": {"query": "b"}})
    assert [c[2] for c in manager.calls] == [{"query": "a"}, {"query": "b"}]


def test_bridge_falls_back_to_the_wrapper_schema():
    ref = McpToolRef("s", "opaque", "mcp.s.opaque", "no schema published")
    tool = McpBridgeTool(_StubManager(), McpClient(_server("s")), ref)
    assert "args" in tool.schema()["properties"]
