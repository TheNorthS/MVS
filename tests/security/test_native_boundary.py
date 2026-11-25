import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mvs.config import validate_configs
from mvs.domain.errors import ShellError
from mvs.domain.native import NativeCommand, NativeImplementation
from mvs.infrastructure.native.bindings import bind, validate_command
from mvs.services.shell_service import ShellService
from tests.e2e.test_native_commands import command, configs


@pytest.mark.parametrize(
    "implementation",
    [
        NativeImplementation("python", "/tmp", ()),
        NativeImplementation("/usr/bin/id", "relative", ()),
        NativeImplementation("/usr/bin/echo", "/tmp", ({"param": "missing"},)),
    ],
)
def test_invalid_native_bindings_fail_closed(implementation):
    cmd = NativeCommand(
        "x", "", {"type": "object", "additionalProperties": False}, {"linux": implementation}
    )
    with pytest.raises(ValueError):
        validate_command(cmd)


def test_config_limits_and_schema(tmp_path):
    cmd = command(tmp_path)
    for changed in [
        replace(cmd, timeout_seconds=0),
        replace(cmd, timeout_seconds=float("nan")),
        replace(cmd, max_output_bytes=0),
        replace(cmd, input_schema={"type": "object"}),
        replace(cmd, implementations={"other": next(iter(cmd.implementations.values()))}),
        replace(cmd, input_schema={**cmd.input_schema, "required": []}),
    ]:
        with pytest.raises(ValueError):
            validate_command(changed)
    group = configs(cmd)["localos"]
    with pytest.raises(ValueError):
        validate_configs([replace(group, command="/bin/sh")])
    with pytest.raises(ValueError):
        validate_configs([replace(group, native_commands=(cmd, cmd))])
    bat = NativeCommand(
        "batch",
        "",
        {"type": "object", "additionalProperties": False},
        {"win32": NativeImplementation("C:\\Windows\\x.cmd", "C:\\Windows")},
    )
    with pytest.raises(ValueError):
        validate_command(bat)
    for executable, argv in [
        ("/bin/sh", ("-c", {"param": "value"})),
        ("C:\\Windows\\System32\\cmd.exe", ("/c", {"param": "value"})),
        ("C:\\Windows\\pwsh.exe", ("-Command", {"param": "value"})),
    ]:
        platform = "linux" if executable.startswith("/") else "win32"
        changed = replace(
            cmd,
            implementations={
                platform: NativeImplementation(
                    executable, "/tmp" if platform == "linux" else "C:\\Windows", argv
                )
            },
        )
        with pytest.raises(ValueError):
            validate_command(changed)


def test_option_nul_path_and_symlink_boundary(tmp_path):
    cmd = command(tmp_path)
    for value in ["--help", "\x00"]:
        with pytest.raises(ShellError):
            bind(cmd, {"value": value})
    for arguments in [{"value": "x", "exe": "/bin/sh"}, {"value": 123}]:
        with pytest.raises(ShellError):
            bind(cmd, arguments)
    cmd = replace(cmd, path_roots={"value": (str(tmp_path / "allowed"),)})
    (tmp_path / "allowed").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ShellError, match="范围"):
        bind(cmd, {"value": str(tmp_path / "allowed" / ".." / "outside")})
    link = tmp_path / "allowed" / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("创建符号链接需要平台权限，普通路径边界已验证")
    with pytest.raises(ShellError, match="范围"):
        bind(cmd, {"value": str(link / "file")})


async def test_timeout_cleans_descendant_process(tmp_path):
    marker = tmp_path / "should-not-exist"
    cmd = command(tmp_path, "tree", "tree", timeout_seconds=0.7)
    service = ShellService(configs(cmd), storage_root=tmp_path / "store")
    await service.start()
    try:
        session = service.sessions.create("local", "local")
        response = await service.execute(
            "/os/localos/tools/tree --params-json '"
            + json.dumps({"value": marker.as_posix()})
            + "'",
            session,
        )
        assert response.error["code"] == "TIMEOUT_UNCERTAIN", response
        pid_file = Path(str(marker) + ".pid")
        assert await asyncio.to_thread(pid_file.exists), "夹具必须确实创建子进程"
        await asyncio.sleep(1.7)
        assert not marker.exists(), "命令后代不能在超时后继续执行"
        assert service.manager.connections["localos"].active_count == 0
    finally:
        await service.close()


async def test_disabled_platform_revoke_and_close(tmp_path):
    cmd = command(tmp_path)
    other = "linux" if sys.platform == "win32" else "win32"
    unavailable = replace(
        cmd,
        name="foreign",
        implementations={
            other: NativeImplementation(
                "/usr/bin/echo" if other == "linux" else "C:\\Windows\\System32\\whoami.exe",
                "/tmp" if other == "linux" else "C:\\Windows",
                ({"param": "value"},),
            )
        },
    )
    service = ShellService(configs(cmd, unavailable), storage_root=tmp_path / "store")
    await service.start()
    try:
        session = service.sessions.create("local", "local")
        assert (await service.execute("tools localos", session)).data == ["/os/localos/tools/echo"]
        sem = service.executor.semaphores["localos"]
        await sem.acquire()
        await sem.acquire()
        pending = asyncio.create_task(service.execute("/os/localos/tools/echo --value x", session))
        await asyncio.sleep(0.02)
        service.policy.grants.clear()
        sem.release()
        sem.release()
        assert (await pending).error["code"] == "POLICY_DENIED"
        assert service.manager.connections["localos"].active_count == 0
    finally:
        await service.close()
