from typing import Protocol

from mvs.domain.models import ResultEnvelope


class MCPTransportClient(Protocol):
    async def list_tools(self, server_id: str, *, refresh: bool = False) -> list[dict]: ...
    async def call_tool(self, server_id: str, name: str, arguments: dict) -> dict: ...
    async def close(self) -> None: ...


class ResultStorage(Protocol):
    """Replace local storage with a tenant-aware external backend without SDK coupling."""

    async def put(
        self,
        result: ResultEnvelope,
        owner: tuple[str, str],
        ttl_s: int = 3600,
        assets: dict | None = None,
    ) -> str: ...
    async def get(self, result_id: str, principal: tuple[str, str]) -> ResultEnvelope: ...
    async def slice(
        self, result_id: str, principal: tuple[str, str], offset: int, limit: int
    ) -> object: ...
    async def get_asset(
        self, result_id: str, asset_id: str, principal: tuple[str, str]
    ) -> dict: ...
    async def delete_expired(self) -> int: ...
    def close(self) -> None: ...
