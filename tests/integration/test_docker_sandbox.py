import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mvs.domain.models import ServerConfig
from mvs.domain.native import NativeCommand, NativeImplementation
from mvs.infrastructure.native.process import run_process
from mvs.services.shell_service import ShellService

IMAGE = os.environ.get("MVS_TEST_SANDBOX_IMAGE")
pytestmark = pytest.mark.skipif(not IMAGE, reason="需要真实Docker沙箱测试镜像")


def command(root: Path, script: str) -> NativeCommand:
    # Linux临时目录默认0700；明确允许容器的65534用户读取这份测试工作区。
    root.chmod(0o755)
    return NativeCommand(
        "probe",
        "真实容器边界验证",
        {"type": "object", "additionalProperties": False},
        {
            sys.platform: NativeImplementation(
                "/usr/local/bin/python", str(root), ("/workspace/" + script,)
            )
        },
        timeout_seconds=15,
        sandbox_image=IMAGE,
        memory_limit_mb=128,
    )


async def test_container_readonly_network_user_limits_and_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("MVS_UNRELATED_SECRET", "must-not-be-inherited")
    folder = tmp_path / "含空格 workspace"
    folder.mkdir()
    (folder / "data.txt").write_text("容器可以读取白名单文件", encoding="utf-8")
    (folder / "probe.py").write_text(
        """
import os,json,pathlib,socket
report={'uid':os.getuid(),'cwd':os.getcwd(),'file':pathlib.Path('data.txt').read_text(encoding='utf-8'),
        'interfaces':sorted(p.name for p in pathlib.Path('/sys/class/net').iterdir()),
        'memory':pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip(),
        'pids':pathlib.Path('/sys/fs/cgroup/pids.max').read_text().strip(),
        'cpu':pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
        'status':pathlib.Path('/proc/self/status').read_text(),
        'secret':os.environ.get('MVS_UNRELATED_SECRET'),
        'docker_config':os.environ.get('DOCKER_CONFIG')}
for label,path in [('root','/escape'),('workspace','/workspace/created')]:
    try: pathlib.Path(path).write_text('not allowed');report[label]='writable'
    except OSError: report[label]='readonly'
print(json.dumps(report,ensure_ascii=False))
""",
        encoding="utf-8",
    )
    raw = await run_process(command(folder, "probe.py"), {})
    assert not raw["is_error"], raw
    data = json.loads(raw["structured_content"]["stdout"])
    assert data["uid"] == 65534 and data["cwd"] == "/workspace"
    assert data["file"] == "容器可以读取白名单文件"
    assert data["root"] == data["workspace"] == "readonly"
    assert data["interfaces"] == ["lo"]
    assert int(data["memory"]) == 128 * 1024 * 1024 and int(data["pids"]) == 64
    quota, period = map(int, data["cpu"].split())
    assert quota == period  # 允许占用至多一个CPU核。
    status = dict(line.split(":", 1) for line in data["status"].splitlines())
    assert int(status["CapEff"].strip(), 16) == 0 and status["NoNewPrivs"].strip() == "1"
    assert data["secret"] is data["docker_config"] is None
    assert not (folder / "created").exists()


async def test_docker_timeout_cancel_and_output_limit_cleanup(tmp_path):
    before = await asyncio.to_thread(
        subprocess.check_output,
        ["docker", "ps", "-aq", "--filter", "label=mvs.backend=native"],
        text=True,
    )
    (tmp_path / "sleep.py").write_text('import time\nprint("ready",flush=True)\ntime.sleep(60)')
    config = command(tmp_path, "sleep.py")
    with pytest.raises(TimeoutError):
        await run_process(replace(config, timeout_seconds=2), {})
    task = asyncio.create_task(run_process(config, {}))
    await asyncio.sleep(2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    (tmp_path / "flood.py").write_text('while True: print("x"*8192,flush=True)')
    service = ShellService(
        {
            "sandbox": ServerConfig(
                "sandbox",
                transport="native",
                allowed_tools=("probe",),
                native_commands=(replace(command(tmp_path, "flood.py"), max_output_bytes=1024),),
            )
        },
        storage_root=tmp_path / "store",
    )
    await service.start()
    try:
        session = service.sessions.create("local", "local")
        result = await service.execute("/os/sandbox/tools/probe", session)
        assert result.error["code"] == "RESULT_TOO_LARGE", result
        assert service.manager.connections["sandbox"].active_count == 0
    finally:
        await service.close()
    after = await asyncio.to_thread(
        subprocess.check_output,
        ["docker", "ps", "-aq", "--filter", "label=mvs.backend=native"],
        text=True,
    )
    assert set(after.split()) == set(before.split()), "命令结束后不能遗留沙箱容器"


async def test_repeated_cancellation_waits_for_real_container_cleanup(tmp_path, monkeypatch):
    from mvs.infrastructure.native import process as native_process

    entered, release = asyncio.Event(), asyncio.Event()
    remove = native_process._remove_container
    removed = []

    async def slow_remove(executable, name, env):
        entered.set()
        await release.wait()
        await remove(executable, name, env)
        removed.append(name)

    monkeypatch.setattr(native_process, "_remove_container", slow_remove)
    (tmp_path / "sleep.py").write_text("import time\ntime.sleep(60)")
    task = asyncio.create_task(run_process(command(tmp_path, "sleep.py"), {}))
    try:
        await asyncio.sleep(2)
        task.cancel()
        await asyncio.wait_for(entered.wait(), 10)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "重复取消不能跳过容器回收"
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(removed) == 1
    remaining = await asyncio.to_thread(
        subprocess.check_output,
        ["docker", "ps", "-aq", "--filter", f"name=^/{removed[0]}$"],
        text=True,
    )
    assert not remaining.strip()


async def test_container_dynamic_host_path_maps_inside_mount(tmp_path):
    tmp_path.chmod(0o755)
    source = tmp_path / "中文 file.txt"
    source.write_text("mapped file contents", encoding="utf-8")
    configured = NativeCommand(
        "cat",
        "按根目录约束读文件",
        {
            "type": "object",
            "properties": {"file": {"type": "string"}},
            "required": ["file"],
            "additionalProperties": False,
        },
        {sys.platform: NativeImplementation("/bin/cat", str(tmp_path), ({"param": "file"},))},
        sandbox_image=IMAGE,
        path_roots={"file": (str(tmp_path),)},
    )
    result = await run_process(configured, {"file": str(source)})
    assert result["structured_content"]["stdout"] == "mapped file contents", result
