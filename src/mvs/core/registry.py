import asyncio
import copy
import hashlib
import json
import os
import time

from mvs.core.schema_adapter import check_schema
from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig, ToolDescriptor
from mvs.domain.ports import MCPTransportClient
from mvs.domain.telemetry import Telemetry


class Registry:
    def __init__(
        self,
        configs: dict[str, ServerConfig],
        transport: MCPTransportClient,
        telemetry: Telemetry | None = None,
    ) -> None:
        self.telemetry = telemetry or Telemetry()
        self.configs = configs
        self.transport = transport
        self._tools: dict[tuple[str, str], ToolDescriptor] = {}
        self.status: dict[str, str] = dict.fromkeys(configs, "offline")
        self.locks = {key: asyncio.Lock() for key in configs}

    def snapshot(self) -> dict[tuple[str, str], ToolDescriptor]:
        return copy.deepcopy(self._tools)

    def get(self, server_id: str, name: str) -> ToolDescriptor:
        if self.status.get(server_id) != "online":
            raise ShellError("SERVER_OFFLINE", "Server is offline")
        if (server_id, name) not in self._tools:
            raise ShellError("NOT_FOUND", "Tool not found")
        return copy.deepcopy(self._tools[server_id, name])

    async def refresh(self, server_id: str) -> None:
        started = time.monotonic()
        status = "error"
        try:
            with self.telemetry.span("mvs.registry.refresh", server=server_id):
                await self._refresh(server_id)
            status = "success"
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        finally:
            self.telemetry.registry_finished(server_id, status, time.monotonic() - started)

    async def _refresh(self, server_id: str) -> None:
        async with self.locks[server_id]:
            try:
                items = await self.transport.list_tools(server_id, refresh=True)
                names = set()
                for item in items:
                    name = item["name"]
                    if not name or len(name.encode()) > 1024 or name in names:
                        raise ShellError("MCP_PROTOCOL_ERROR", "Invalid or duplicate tool name")
                    names.add(name)
                    schema = item["input_schema"]
                    for candidate in (schema, item["output_schema"]):
                        if candidate is None:
                            continue
                        if os.environ.get("MVS_ISOLATED_VALIDATION") == "1":
                            from mvs.infrastructure.native.isolated import isolated_operation

                            await isolated_operation(
                                {"operation": "check_schema", "schema": candidate}
                            )
                        else:
                            check_schema(candidate)
                revision = hashlib.sha256(
                    json.dumps(sorted(items, key=lambda x: x["name"]), sort_keys=True).encode()
                ).hexdigest()
                updated = {key: value for key, value in self._tools.items() if key[0] != server_id}
                for item in items:
                    updated[server_id, item["name"]] = ToolDescriptor(
                        server_id=server_id,
                        revision=revision,
                        discovered_at=time.time(),
                        backend="native"
                        if self.configs[server_id].transport == "native"
                        else "mcp",
                        **item,
                    )
                self._tools = updated
                self.status[server_id] = "online"
            except Exception as exc:
                self.status[server_id] = "offline"
                if isinstance(exc, ShellError):
                    raise
                raise ShellError("SERVER_OFFLINE", "Tool discovery failed") from None

    async def discover(self) -> None:
        await asyncio.gather(
            *(self.refresh(key) for key, config in self.configs.items() if config.enabled),
            return_exceptions=True,
        )
