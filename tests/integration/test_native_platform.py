import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mvs.config import load_config
from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig, ToolInvocation
from mvs.domain.native import NativeCommand, NativeImplementation
from mvs.infrastructure.native.bindings import validate_command
from mvs.services.shell_service import ShellService
from tests.e2e.test_native_commands import command, configs

POWERSHELL = (
    Path(os.environ.get("SystemRoot", "C:/Windows"))
    / "System32/WindowsPowerShell/v1.0/powershell.exe"
)
PS_SCRIPT = Path("examples/native/system_info.ps1").resolve()


def test_interpreter_cannot_bind_dynamic_source(tmp_path):
    cmd = command(tmp_path)
    impl = next(iter(cmd.implementations.values()))
    with pytest.raises(ValueError, match="绝对脚本"):
        validate_command(
            replace(
                cmd, implementations={sys.platform: replace(impl, argv=("-c", {"param": "value"}))}
            )
        )


async def test_native_and_mcp_coexist(tmp_path):
    cs = {**load_config("configs/servers.example.yaml"), **configs(command(tmp_path))}
    service = ShellService(cs, storage_root=tmp_path / "store")
    await service.start()
    try:
        session = service.sessions.create("local", "local")
        assert (await service.execute("ls /mcp", session)).data == ["demo/"]
        assert (await service.execute("ls /os", session)).data == ["localos/"]
        assert (await service.execute("/mcp/demo/tools/add --a 2 --b 3", session)).data == {
            "result": 5
        }
        assert (
            await service.execute("/os/localos/tools/echo --value mixed", session)
        ).status == "success"
        old = service.registry.get("localos", "echo")
        connection = service.manager.connections["localos"]
        connection.config = replace(
            connection.config,
            native_commands=(replace(connection.config.native_commands[0], timeout_seconds=11),),
        )
        await service.registry.refresh("localos")
        with pytest.raises(ShellError) as exc:
            await service.executor.invoke(
                ToolInvocation("localos", "echo", {"value": "x"}, old.revision, "req")
            )
        assert exc.value.code == "TOOL_CHANGED"
    finally:
        await service.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 专用固定脚本验证")
async def test_powershell_fixed_script(tmp_path):
    cmd = NativeCommand(
        "system_info",
        "固定脚本读取系统信息",
        {"type": "object", "additionalProperties": False},
        {
            "win32": NativeImplementation(
                str(POWERSHELL),
                str(tmp_path),
                ("-NoProfile", "-NonInteractive", "-File", str(PS_SCRIPT)),
            )
        },
    )
    service = ShellService(
        {
            "host": ServerConfig(
                "host", transport="native", native_commands=(cmd,), allowed_tools=("system_info",)
            )
        },
        storage_root=tmp_path / "store",
    )
    await service.start()
    try:
        session = service.sessions.create("local", "local")
        result = await service.execute("/os/host/tools/system_info", session)
        assert result.status == "success", result
        data = json.loads(result.data["stdout"])
        assert data["machine_name"] and data["process_count"] > 0
    finally:
        await service.close()
