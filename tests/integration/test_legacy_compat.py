import asyncio
import os
import sys
from pathlib import Path

import pytest

from mvs.domain.models import ServerConfig
from mvs.services.shell_service import ShellService

LEGACY = Path(
    os.environ.get(
        "MVS_LEGACY_PYTHON",
        ".tools/legacy/Scripts/python.exe"
        if sys.platform == "win32"
        else ".tools/legacy/bin/python",
    )
)
# POSIX虚拟环境的python通常是符号链接，resolve会绕过pyvenv.cfg而使用系统环境。
LEGACY = LEGACY.absolute()
LEGACY_SERVER = Path("tests/fixtures/legacy_server.py").resolve()
LEGACY_CLIENT = Path("tests/fixtures/legacy_client.py").resolve()


@pytest.mark.skipif(not LEGACY.exists(), reason="Install isolated legacy fixture environment first")
async def test_v2_client_to_real_v1_server(tmp_path):
    service = ShellService(
        {
            "demo": ServerConfig(
                "demo",
                command=str(LEGACY),
                args=(str(LEGACY_SERVER),),
                allowed_tools=("add",),
            )
        },
        storage_root=tmp_path,
    )
    await service.start()
    try:
        session = service.sessions.create("local", "local")
        result = await service.execute("/mcp/demo/tools/add --a 2 --b 3", session)
        assert result.data == {"result": 5}, result
        version = service.manager.connections["demo"].connected().protocol_version
        assert version in {"2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"}
    finally:
        await service.close()


@pytest.mark.skipif(not LEGACY.exists(), reason="Install isolated legacy fixture environment first")
async def test_v1_client_to_real_v2_server():
    process = await asyncio.create_subprocess_exec(
        str(LEGACY),
        str(LEGACY_CLIENT),
        sys.executable,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
        assert process.returncode == 0, stderr.decode(errors="replace")
        assert b"passed" in stdout
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
