import asyncio
import socket

import uvicorn
from mcp.server import MCPServer

from mvs.domain.models import ServerConfig
from mvs.services.shell_service import ShellService


async def test_real_http_transport(tmp_path):
    server = MCPServer("http-fixture")

    @server.tool()
    def add(a: int, b: int) -> int:
        return a + b

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = server.streamable_http_app()
    host = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    task = asyncio.create_task(host.serve(sockets=[sock]))
    service = ShellService(
        {
            "demo": ServerConfig(
                "demo",
                transport="streamable_http",
                url=f"http://127.0.0.1:{port}/mcp",
                http_allowed_hosts=("127.0.0.1",),
                http_allow_private=True,
                allowed_tools=("add",),
            )
        },
        storage_root=tmp_path,
    )
    try:
        async with asyncio.timeout(10):
            while not host.started:  # noqa: ASYNC110 - uvicorn exposes a bool, not a ready event
                await asyncio.sleep(0.01)
        await service.start()
        session = service.sessions.create("local", "local")
        result = await service.execute("/mcp/demo/tools/add --a 4 --b 5", session)
        assert result.data == {"result": 9}, result
        assert service.manager.connections["demo"].connected().protocol_version == "2026-07-28"
    finally:
        await service.close()
        host.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()
