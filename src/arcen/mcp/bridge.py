"""ARCEN — MCP bridge tools (Part 3 + Part 6 composed).

A connected MCP server's tools appear in the ARCEN registry as
``mcp.<server>.<tool>`` — callable by FORGE, sub-agents, and any other
consumer of the frozen Tool schema. The bridge wraps the remote call in
the frozen envelope, hops to the manager's MCP loop, and never raises.
"""

from __future__ import annotations

from .client import McpClient, McpToolRef


def _unwrap(args: dict, schema: dict) -> dict:
    """Accept both shapes: the remote arguments, or ``{"args": {...}}``.

    A server that publishes no schema gets the wrapper from the fallback
    schema; a server that does may still be called with the wrapper, so the
    unwrap is keyed on the argument name rather than on the schema alone.
    """
    if not isinstance(args, dict):
        return {}
    props = schema.get("properties") or {}
    if set(args) == {"args"} and "args" not in props:
        inner = args["args"]
        return inner if isinstance(inner, dict) else {}
    return args


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
        """The server's own schema, when it published one.

        A remote ``inputSchema`` is what the model needs in order to pass the
        right arguments; the generic ``{"args": {...}}`` wrapper is only the
        fallback for servers that publish nothing.
        """
        remote = self._ref.input_schema
        if isinstance(remote, dict) and remote.get("type") == "object":
            return remote
        return {
            "type": "object",
            "properties": {
                "args": {"type": "object", "description": "arguments for the remote tool"},
            },
            "required": [],
        }

    def execute(self, args: dict) -> dict:
        remote_args = _unwrap(args, self.schema())
        tool = self._ref.name
        try:
            return self._manager.call_sync(self._ref.server, tool, remote_args)
        except Exception as exc:  # noqa: BLE001 — envelope contract
            return {"ok": False, "result": None, "error": str(exc)}
