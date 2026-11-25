"""固定可信模板及隔离安装，不接受模型提供任意包名或安装脚本。"""

import asyncio
import shutil
import sys
from pathlib import Path

TEMPLATES: dict[str, dict] = {
    "git": {
        "name": "Git仓库工具",
        "package": "mcp-server-git==2026.11.11",
        "module": "mcp_server_git",
        "tools": ["git_status", "git_log", "git_show", "git_diff_unstaged", "git_diff_staged"],
    },
    "fetch": {
        "name": "网页读取工具",
        "package": "mcp-server-fetch==2026.11.11",
        "module": "mcp_server_fetch",
        "tools": ["fetch"],
    },
}


async def install_template(
    root: Path, template: str, server_id: str, repository: str | None = None
) -> dict:
    import re

    if not re.fullmatch("[a-z][a-z0-9_-]{0,62}", server_id):
        raise ValueError("服务ID格式不正确")
    if template not in TEMPLATES:
        raise ValueError("模板不受信任")
    item = TEMPLATES[template]
    if template == "git" and (
        not repository
        or not Path(repository).is_absolute()
        or not await asyncio.to_thread(Path(repository).is_dir)
    ):
        raise ValueError("Git模板需要现有仓库的绝对路径")
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("未找到uv，请先安装uv")
    target = root / "packages" / template
    python = target / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    commands = []
    if not python.exists():
        commands.append([uv, "venv", str(target), "--python", "3.12"])
    commands.append(
        [uv, "pip", "install", "--python", str(python), item["package"]],
    )
    for argv in commands:
        process = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        try:
            async with asyncio.timeout(300):
                if await process.wait() != 0:
                    raise ValueError("隔离安装失败，请检查网络与uv环境")
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
    args = ["-m", item["module"]]
    if template == "git":
        if (
            not repository
            or not Path(repository).is_absolute()
            or not await asyncio.to_thread(Path(repository).is_dir)
        ):
            raise ValueError("Git模板需要现有仓库的绝对路径")
        args += ["--repository", repository]
    return {
        "id": server_id,
        "transport": "stdio",
        "command": str(python),
        "args": args,
        "allowed_tools": item["tools"],
        "enabled": True,
    }
