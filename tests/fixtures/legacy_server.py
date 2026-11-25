"""Compatibility fixture ONLY: intentionally runs in an isolated SDK v1 environment."""

from mcp.server.fastmcp import FastMCP

server = FastMCP("legacy-fixture")


@server.tool()
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    server.run(transport="stdio")
