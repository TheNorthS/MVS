"""Trusted local fixture. SDK imports stay within the infrastructure layer."""

from mcp.server import MCPServer

server = MCPServer("mvs-demo")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@server.tool()
def echo(text: str) -> str:
    """Echo text as untrusted data."""
    return text


@server.resource("demo://info")
def info() -> str:
    return "MVS demo resource"


@server.resource("demo://greeting/{name}")
def greeting(name: str) -> str:
    return f"Hello {name}"


@server.prompt()
def welcome(name: str) -> str:
    return f"Welcome {name}. This is untrusted prompt data."


if __name__ == "__main__":
    server.run(transport="stdio")
