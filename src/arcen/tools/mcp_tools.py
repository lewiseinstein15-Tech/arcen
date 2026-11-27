"""ARCEN — the model's window onto MCP servers.

Bridged MCP tools appear in the catalog by name once their server connects,
which is enough to call them but not enough to reason about them: a model
facing an empty catalog cannot tell whether MCP is unconfigured, still
connecting, or broken. ``mcp.list`` answers that question with the server
state, the error text, and the tools each server published — read-only, and
cheap enough to call whenever a plan mentions a tool that is not there.
"""

from __future__ import annotations

from pydantic import BaseModel

from .registry import BaseTool


class McpListTool(BaseTool):
    # Not "mcp.<server>.<tool>": that namespace belongs to bridged remote
    # tools, and the registry refuses to let a core tool squat in it.
    name = "server.list"
    description = "Configured MCP servers with their connection state and published tools."
    danger = "safe"

    class Args(BaseModel):
        pass

    def __init__(self, manager=None) -> None:
        self._manager = manager

    def _run(self, a: Args) -> dict:
        if self._manager is None:
            return {"servers": [], "count": 0}
        servers = []
        for name, client in sorted(self._manager.clients.items()):
            servers.append(
                {
                    "name": name,
                    "state": client.state,
                    "error": client.error,
                    "tools": [t.qualified for t in client.tools],
                }
            )
        return {"servers": servers, "count": len(servers)}
