"""执行固定程序和参数数组；有界读取输出，取消时清理拥有的进程组或 Job。"""

import asyncio
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from mvs.domain.errors import ShellError
from mvs.domain.native import NativeCommand
from mvs.infrastructure.native.bindings import bind


async def _stop_process(
    process: asyncio.subprocess.Process | None, readers: list[asyncio.Task], job: Any
) -> None:
    # 先停止本地Docker CLI并排空管道，避免大量输出阻塞daemon的容器删除。
    if job:
        job.close()
    if process is None:
        return
    if sys.platform != "win32":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    for reader in readers:
        reader.cancel()
    await asyncio.gather(*readers, return_exceptions=True)

    async def drain(stream: asyncio.StreamReader | None) -> None:
        if stream is not None:
            while await stream.read(8192):
                continue

    try:
        async with asyncio.timeout(5):
            await asyncio.gather(drain(process.stdout), drain(process.stderr), process.wait())
    except TimeoutError:
        raise ShellError("COMMAND_CLEANUP_FAILED", "进程已请求终止，但输出管道未及时关闭") from None


async def _docker_control(
    executable: str, args: list[str], env: dict[str, str]
) -> tuple[int | None, bytes]:
    process = await asyncio.create_subprocess_exec(
        executable,
        *args,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(30):
            stdout, _ = await process.communicate()
            return process.returncode, stdout
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


async def _remove_container(executable: str, name: str, env: dict[str, str]) -> None:
    try:
        code, _ = await _docker_control(executable, ["rm", "-f", name], env)
        if code:
            # 创建可能失败；只有daemon确认容器不存在才算成功。
            code, output = await _docker_control(
                executable, ["ps", "-aq", "--filter", f"name=^/{name}$"], env
            )
            if code or output.strip():
                raise OSError("container cleanup failed")
    except (OSError, TimeoutError):
        raise ShellError("COMMAND_CLEANUP_FAILED", "无法确认Docker沙箱已回收") from None


async def run_process(
    command: NativeCommand, arguments: dict, credentials: dict | None = None
) -> dict:
    impl, argv = bind(command, arguments)
    env = {
        name: os.environ[name]
        for name in ("SystemRoot", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
        if name in os.environ
    }
    env["PYTHONIOENCODING"] = impl.encoding
    if sys.platform == "win32":
        # Windows系统组件需要这些已知目录/架构变量完成初始化；不继承任意应用凭据。
        for name in (
            "SYSTEMDRIVE",
            "COMSPEC",
            "PATHEXT",
            "PROGRAMDATA",
            "ALLUSERSPROFILE",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "PROGRAMW6432",
            "COMMONPROGRAMFILES",
            "COMMONPROGRAMFILES(X86)",
            "COMMONPROGRAMW6432",
            "PROCESSOR_ARCHITECTURE",
            "PROCESSOR_ARCHITEW6432",
            "NUMBER_OF_PROCESSORS",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "PATH",
            "PSModulePath",
            "OS",
            "COMPUTERNAME",
        ):
            if name in os.environ:
                env[name] = os.environ[name]
    try:
        env.update(
            {
                key: (credentials or {}).get(ref) or os.environ[ref]
                for key, ref in impl.env_refs.items()
            }
        )
    except KeyError:
        raise ShellError("COMMAND_UNAVAILABLE", "缺少原生命令需要的环境变量") from None
    job: Any = None
    options: dict[str, Any] = {}
    if sys.platform == "win32":
        from mvs.infrastructure.native.windows_job import WindowsJob

        options["creationflags"] = subprocess.CREATE_NO_WINDOW | 0x00000004  # CREATE_SUSPENDED
    else:
        options["start_new_session"] = True
    executable = impl.executable
    container_name = None
    create_args = None
    if command.sandbox_image:
        docker = shutil.which("docker")
        if not docker:
            raise ShellError("COMMAND_UNAVAILABLE", "未安装Docker容器运行时")
        container_name = "mvs-" + uuid4().hex
        mounts = {str(await asyncio.to_thread(Path(impl.cwd).resolve)): "/workspace"}
        for root in [root for roots in command.path_roots.values() for root in roots]:
            mounts.setdefault(
                str(await asyncio.to_thread(Path(root).resolve)), f"/mvs/root{len(mounts)}"
            )
        container_argv = [
            "create",
            "--pull=never",
            "--log-driver=none",
            "--name",
            container_name,
            "--label",
            "mvs.backend=native",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory",
            f"{command.memory_limit_mb or 256}m",
            "--cpus",
            "1",
            "--user",
            "65534:65534",
            "--workdir",
            "/workspace",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
        ]
        if not command.sandbox_network:
            container_argv += ["--network", "none"]
        for mount, dest in mounts.items():
            if "," in mount:
                raise ShellError("INVALID_ARGUMENT", "容器挂载路径不能包含逗号")
            container_argv += ["--mount", f"type=bind,src={mount},dst={dest},readonly"]
        mapped = []
        for value in argv:
            replacement = value
            if Path(value).is_absolute():
                for mount, dest in sorted(
                    mounts.items(), key=lambda item: len(item[0]), reverse=True
                ):
                    try:
                        resolved = await asyncio.to_thread(Path(value).resolve)
                        relative = resolved.relative_to(Path(mount))
                    except ValueError:
                        continue
                    replacement = dest + ("/" + relative.as_posix() if relative.parts else "")
                    break
            mapped.append(replacement)
        argv = mapped
        for key in impl.env_refs:
            container_argv += ["--env", key]
        create_args = [*container_argv, command.sandbox_image, executable, *argv]
        argv = ["start", "--attach", container_name]
        executable = docker
        # Docker CLI需要宿主连接配置；只有显式 --env 的变量会进入容器。
        for key in (
            "HOME",
            "USERPROFILE",
            "DOCKER_CONFIG",
            "DOCKER_CONTEXT",
            "DOCKER_HOST",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
            "PATH",
        ):
            if key in os.environ:
                env[key] = os.environ[key]
    if (
        not container_name
        and sys.platform != "win32"
        and (command.memory_limit_mb or command.cpu_time_seconds)
    ):
        argv = [
            str(Path(__file__).with_name("posix_launcher.py")),
            str(command.memory_limit_mb or 0),
            str(command.cpu_time_seconds or 0),
            executable,
            *argv,
        ]
        executable = sys.executable
    process = None
    readers: list[asyncio.Task] = []
    total = 0

    async def read(stream: asyncio.StreamReader) -> bytes:
        nonlocal total
        parts = []
        while block := await stream.read(8192):
            total += len(block)
            if total > command.max_output_bytes:
                raise ShellError("RESULT_TOO_LARGE", "原生命令输出超过配置上限，已停止进程")
            parts.append(block)
        return b"".join(parts)

    if sys.platform == "win32":
        job = WindowsJob(
            command.memory_limit_mb if not command.sandbox_image else None,
            command.cpu_time_seconds if not command.sandbox_image else None,
        )
    launch: asyncio.Task[asyncio.subprocess.Process] | None = None
    creating: asyncio.Task[tuple[int | None, bytes]] | None = None

    async def cleanup_process() -> None:
        nonlocal process
        if creating is not None:
            # 创建请求有自己的有界超时；取消不能让daemon迟到的创建留下孤立容器。
            try:
                await creating
            except (OSError, TimeoutError):
                pass
        try:
            if process is None and launch is not None:
                try:
                    process = await launch
                except (OSError, asyncio.CancelledError):
                    process = None
            await _stop_process(process, readers, job)
        finally:
            if container_name:
                await _remove_container(executable, container_name, env)

    try:
        if create_args:
            creating = asyncio.create_task(_docker_control(executable, create_args, env))
            code, _ = await asyncio.shield(creating)
            if code:
                raise ShellError(
                    "COMMAND_UNAVAILABLE", "无法创建Docker沙箱，请检查本地镜像和挂载配置"
                )
        launch = asyncio.create_task(
            asyncio.create_subprocess_exec(
                executable,
                *argv,
                cwd=impl.cwd,
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=16384,
                **options,
            )
        )
        # 屏蔽启动窗口的取消，确保拿到进程句柄后由 finally 负责清理。
        process = await asyncio.shield(launch)
        if job:
            job.assign_and_resume(process.pid)
        assert process.stdout is not None and process.stderr is not None
        readers = [
            asyncio.create_task(read(process.stdout)),
            asyncio.create_task(read(process.stderr)),
        ]
        async with asyncio.timeout(command.timeout_seconds):
            stdout, stderr = await asyncio.gather(*readers)
            code = await process.wait()
        data = {
            "stdout": stdout.decode(impl.encoding, errors="replace"),
            "stderr": stderr.decode(impl.encoding, errors="replace"),
            "exit_code": code,
            "platform": sys.platform,
            "output_bytes": total,
        }
        return {
            "is_error": code != 0,
            "structured_content": data,
            "content": [],
            "backend": "native",
            "error_code": "COMMAND_FAILED" if code != 0 else None,
        }
    except TimeoutError:
        raise
    except OSError:
        raise ShellError("COMMAND_UNAVAILABLE", "原生命令无法启动或进程隔离初始化失败") from None
    finally:
        # 清理在独立任务内完成，外层超时/重复取消不能中断回收。
        cleanup_task = asyncio.create_task(cleanup_process())
        cancelled = False
        while True:
            try:
                await asyncio.shield(cleanup_task)
                break
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError
