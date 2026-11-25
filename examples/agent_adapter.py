"""Framework-neutral single-tool integration; no model key is required."""

from dataclasses import asdict

from mvs.domain.models import SessionContext
from mvs.services.shell_service import ShellService

TOOL = {
    "name": "virtual_shell",
    "description": "执行已授权工具；用 ls /mcp、ls /os 和 help 发现 MCP 与受管原生命令。",
    "parameters": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
        "additionalProperties": False,
    },
}


async def virtual_shell(command: str, service: ShellService, session: SessionContext) -> dict:
    return {"untrusted_tool_data": asdict(await service.execute(command, session))}
