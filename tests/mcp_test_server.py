"""A self-contained MCP stdio test server — Python standard library ONLY.

Used by tests/test_mcp.py. The earlier version was built on FastMCP
(``mcp.server.fastmcp``), which made the test suite depend on the MCP
SDK being importable *inside the spawned subprocess* — on machines
without the SDK (or with a broken FastMCP stack) the child died on
import, the handshake never completed, and connect() returned False
with no visible cause.

This rewrite speaks the same wire protocol with zero dependencies:

- transport: newline-delimited JSON-RPC 2.0 over stdin/stdout — the
  exact framing the MCP Python SDK's stdio_client uses (it splits
  stdout chunks on "\\n" and writes ``json + "\\n"``).
- methods: initialize, notifications/initialized (silent), tools/list,
  tools/call.
- tools: echo(text) -> text, add(a, b) -> a+b — the two tools the
  tests assert on.

Spawned as ``sys.executable tests/mcp_test_server.py`` (absolute
path), so it works wherever pytest runs: no npx, no uvx, no node,
no cwd or PATH assumptions.
"""

from __future__ import annotations

import json
import sys

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "arcen-test-server", "version": "0.1.0"}

TOOLS = [
    {
        "name": "echo",
        "description": "Echo the text back.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "add",
        "description": "Add two integers.",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    },
]


def _tool_call(name: str, args: dict) -> dict:
    """Execute one tool. Returns the tools/call result object."""
    if name == "echo":
        text = str(args.get("text", ""))
        return {"content": [{"type": "text", "text": text}], "isError": False}
    if name == "add":
        total = int(args.get("a", 0)) + int(args.get("b", 0))
        return {"content": [{"type": "text", "text": str(total)}], "isError": False}
    return {
        "content": [{"type": "text", "text": f"unknown tool {name!r}"}],
        "isError": True,
    }


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    method = msg.get("method")
    rid = msg.get("id")

    if rid is None:  # notification — never answered
        return None

    if method == "initialize":
        params = msg.get("params") or {}
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                # echo the client's requested version — what real servers
                # do for backwards compatibility
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = msg.get("params") or {}
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": _tool_call(params.get("name", ""), params.get("arguments") or {}),
        }

    return {
        "jsonrpc": "2.0",
        "id": rid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    # stderr is free for logging — the SDK client never parses it
    print("arcen-test-server: stdio ready (stdlib only)", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            # unparseable frame: answer with a protocol error if it has an id
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": f"Parse error: {exc}"},
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
