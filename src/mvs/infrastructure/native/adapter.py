"""原生命令后端；目录来自管理员定义，执行由统一服务完成授权后发起。"""

import asyncio
import copy
import hashlib
import json
import sys
from dataclasses import asdict

from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig
from mvs.infrastructure.native.bindings import validate_command
from mvs.infrastructure.native.process import run_process


class NativeConnection:
    def __init__(self, config: ServerConfig, credentials: dict | None = None) -> None:
        self.credentials = credentials or {}
        self.config = config
        self.client = False
        self.tasks: set[asyncio.Task] = set()

    @property
    def active_count(self) -> int:
        return len(self.tasks)

    async def start(self) -> None:
        names = set()
        for command in self.config.native_commands:
            validate_command(command)
            if command.name in names:
                raise ValueError("原生命令名称重复")
            names.add(command.name)
        self.client = True

    async def list_tools(self, *, refresh: bool = False) -> list[dict]:
        items = []
        for command in self.config.native_commands:
            if not command.enabled or sys.platform not in command.implementations:
                continue
            # 将完整管理员绑定的哈希纳入目录revision，程序/参数规则变化也使旧计划失效。
            binding_hash = hashlib.sha256(
                json.dumps(asdict(command), sort_keys=True).encode()
            ).hexdigest()
            items.append(
                {
                    "name": command.name,
                    "title": command.name,
                    "description": command.description,
                    "input_schema": copy.deepcopy(command.input_schema),
                    "output_schema": None,
                    "annotations": {"mvs_backend": "native", "binding_hash": binding_hash},
                }
            )
        return items

    async def list_catalog(self) -> dict[str, list[dict]]:
        return {}

    async def call_tool(self, name: str, arguments: dict) -> dict:
        if not self.client:
            raise ShellError("SERVER_OFFLINE", "原生命令组已关闭")
        command = next((item for item in self.config.native_commands if item.name == name), None)
        if command is None or not command.enabled:
            raise ShellError("NOT_FOUND", "原生命令不存在或已禁用")
        task = asyncio.create_task(run_process(command, arguments, self.credentials))
        self.tasks.add(task)
        try:
            return await task
        finally:
            self.tasks.discard(task)

    async def read_resource(self, uri: str) -> dict:
        raise ShellError("INVALID_PATH", "原生命令组没有 MCP 资源")

    async def get_prompt(self, name: str, args: dict) -> dict:
        raise ShellError("INVALID_PATH", "原生命令组没有 MCP 提示词")

    async def close(self) -> None:
        self.client = False
        active = list(self.tasks)
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
