import sys
from importlib.metadata import version

from mcp import Client, StdioServerParameters


async def test_real_sdk_v2_stdio():
    assert version("mcp").split(".")[0] == "2"
    target = StdioServerParameters(
        command=sys.executable, args=["-m", "mvs.infrastructure.mcp.demo_server"]
    )
    async with Client(target) as client:
        page = await client.list_tools()
        tools = {tool.name: tool for tool in page.tools}
        assert {"add", "echo"} <= tools.keys()
        assert tools["add"].input_schema["properties"]["a"]["type"] == "integer"
        assert page.next_cursor is None
        result = await client.call_tool("add", {"a": 2, "b": 3})
        assert result.is_error is False
        assert result.structured_content == {"result": 5}
        assert client.protocol_version == "2026-07-28"
        failure = await client.call_tool("add", {"a": "invalid", "b": 3})
        assert failure.is_error is True
