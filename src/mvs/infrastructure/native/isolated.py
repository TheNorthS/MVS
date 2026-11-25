import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from mvs.domain.errors import ShellError


async def isolated_operation(payload: dict) -> object:
    worker = str(Path(__file__).with_name("validation_worker.py"))
    argv = [sys.executable, worker]
    options: dict[str, Any] = {}
    job = None
    if sys.platform == "win32":
        from mvs.infrastructure.native.windows_job import WindowsJob

        job = WindowsJob(256, 3)
        options["creationflags"] = 0x08000000 | 0x00000004
    else:
        options["start_new_session"] = True
        argv = [
            sys.executable,
            str(Path(__file__).with_name("posix_launcher.py")),
            "256",
            "3",
            *argv,
        ]
    process = None
    launch = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            **options,
        )
    )
    try:
        process = await asyncio.shield(launch)
        if job:
            job.assign_and_resume(process.pid)
        async with asyncio.timeout(5):
            stdout, _ = await process.communicate(json.dumps(payload).encode())
        if process.returncode != 0:
            raise ShellError("LIMIT_EXCEEDED", "隔离校验超过资源限制或工作进程失败")
        result = json.loads(stdout)
        if "error" in result:
            raise ShellError(result["error"]["code"], result["error"]["message"])
        return result["result"]
    except TimeoutError:
        raise ShellError("LIMIT_EXCEEDED", "校验或管道计算超过时间限制") from None
    finally:
        if process is None:
            try:
                process = await launch
            except (OSError, asyncio.CancelledError):
                process = None
        if job:
            job.close()
        if process:
            if sys.platform != "win32":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.returncode is None:
                process.kill()
            await process.communicate()
