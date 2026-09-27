"""ARCEN — MCP bridge tools (Part 3 + Part 6 composed).

A connected MCP server's tools appear in the ARCEN registry as
``mcp.<server>.<tool>`` — callable by FORGE, sub-agents, and any other
consumer of the frozen Tool schema. The bridge wraps the remote call in
the frozen envelope, hops to the manager's MCP loop, and never raises.
"""

from __future__ import annotations

from .client import McpClient, McpToolRef


class McpBridgeTool:
    """The frozen Tool schema over a remote MCP tool."""

    def __init__(self, manager, client: McpClient, ref: McpToolRef) -> None:
        self._manager = manager
        self._client = client
        self._ref = ref
        self.name = ref.qualified
        self.description = f"[mcp:{ref.server}] {ref.description or 'remote MCP tool'}"
        self.version = "1.0.0"
        self.danger = "sandboxed"

    def schema(self) -> dict:
        """Remote schemas are taken as-is (declared by the server)."""
        return {
            "type": "object",
            "properties": {
                "args": {"type": "object", "description": "arguments for the remote tool"},
            },
            "required": [],
        }

    def execute(self, args: dict) -> dict:
        remote_args = args.get("args", args if "args" not in args else {})
        tool = self._ref.name
        try:
            return self._manager.call_sync(self._ref.server, tool, remote_args)
        except Exception as exc:  # noqa: BLE001 — envelope contract
            return {"ok": False, "result": None, "error": str(exc)}
