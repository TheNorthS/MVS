from types import SimpleNamespace

import pytest

from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig
from mvs.infrastructure.mcp.sdk_v2_adapter import SDKConnection


async def test_three_pages_and_cycle():
    connection = SDKConnection(ServerConfig("demo", command="python"))
    calls = []

    class Client:
        cycle = False

        async def list_tools(self, cursor=None, cache_mode=None):
            calls.append((cursor, cache_mode))
            n = int(cursor or 0)
            tool = SimpleNamespace(
                name=str(n),
                title=None,
                description=None,
                input_schema={},
                output_schema=None,
                annotations=None,
            )
            return SimpleNamespace(
                tools=[tool], next_cursor="1" if self.cycle else str(n + 1) if n < 2 else None
            )

    client = Client()
    connection.client = client
    assert len(await connection.list_tools(refresh=True)) == 3
    assert calls == [(None, "refresh"), ("1", "refresh"), ("2", "refresh")]
    client.cycle = True
    with pytest.raises(ShellError) as exc:
        await connection.list_tools()
    assert exc.value.code == "MCP_PROTOCOL_ERROR"
