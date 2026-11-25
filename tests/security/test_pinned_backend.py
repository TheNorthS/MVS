from unittest.mock import AsyncMock

import pytest
from httpcore2._backends.auto import AutoBackend

from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig
from mvs.infrastructure.mcp.pinned_http import PinnedBackend


async def test_verified_ip_used_for_socket(monkeypatch):
    import asyncio

    loop = asyncio.get_running_loop()
    resolve = AsyncMock(return_value=[(2, 1, 6, "", ("8.8.8.8", 443))])
    connect = AsyncMock(return_value="stream")
    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
    backend = PinnedBackend(
        ServerConfig("http", transport="streamable_http", http_allowed_hosts=("example.org",))
    )
    assert await backend.connect_tcp("example.org", 443) == "stream"
    assert connect.call_args.args[0] == "8.8.8.8"
    resolve.return_value = [(2, 1, 6, "", ("127.0.0.1", 443))]
    with pytest.raises(ShellError):
        await backend.connect_tcp("example.org", 443)
    assert connect.call_count == 1
