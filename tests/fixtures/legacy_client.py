"""Verify an actual SDK v1 client against the production SDK v2 demo server."""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    target = StdioServerParameters(
        command=sys.argv[1], args=["-m", "mvs.infrastructure.mcp.demo_server"]
    )
    async with stdio_client(target) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        tools = await client.list_tools()
        assert "add" in {tool.name for tool in tools.tools}
        result = await client.call_tool("add", {"a": 4, "b": 5})
        assert not result.isError  # legacy fixture intentionally exercises old wire client
        print("legacy-client-to-v2-server: passed")


asyncio.run(main())
