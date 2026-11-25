import asyncio
from typing import Any

from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig
from mvs.infrastructure.mcp.sdk_v2_adapter import SDKConnection
from mvs.infrastructure.native.adapter import NativeConnection


class ClientManager:
    def __init__(
        self,
        configs: dict[str, ServerConfig],
        credentials: dict | None = None,
        oauth_resolver: Any = None,
    ) -> None:
        self.credentials = credentials or {}
        self.oauth_resolver = oauth_resolver
        self.configs = configs
        self.connections: dict[str, SDKConnection | NativeConnection] = {}
        self.locks = {key: asyncio.Lock() for key in configs}

    async def connect(self, server_id: str) -> SDKConnection | NativeConnection:
        async with self.locks[server_id]:
            connection = self.connections.get(server_id)
            if connection and connection.client:
                return connection
            config = self.configs[server_id]
            if not config.enabled:
                raise ShellError("SERVER_OFFLINE", "Server disabled")
            if connection:
                await connection.close()
            connection = (
                NativeConnection(config, self.credentials)
                if config.transport == "native"
                else SDKConnection(config, self.credentials, self.oauth_resolver)
            )
            await connection.start()
            self.connections[server_id] = connection
            return connection

    async def list_tools(self, server_id: str, *, refresh: bool = False) -> list[dict]:
        return await (await self.connect(server_id)).list_tools(refresh=refresh)

    async def call_tool(self, server_id: str, name: str, arguments: dict) -> dict:
        connection = self.connections.get(server_id)
        if connection is None:
            raise ShellError("SERVER_OFFLINE", "Server is offline")
        return await connection.call_tool(name, arguments)

    async def disconnect(self, server_id: str) -> None:
        connection = self.connections.pop(server_id, None)
        if connection:
            await connection.close()

    async def close(self) -> None:
        for server_id in reversed(list(self.connections)):
            await self.disconnect(server_id)
