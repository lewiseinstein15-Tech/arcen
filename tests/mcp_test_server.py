"""A minimal MCP stdio server used by tests/test_mcp.py.

Built with the MCP Python SDK's server framework — two tools: echo, add.
This is the "test MCP server" the ticket connects to.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("test-server")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the text back."""
    return text


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


if __name__ == "__main__":
    mcp.run()
