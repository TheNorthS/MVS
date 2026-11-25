"""显式HTTPS发布清单、SHA256校验和保留上一安装包的升级流程。"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from packaging.version import Version


def check_release(url: str) -> dict:
    if urlsplit(url).scheme != "https":
        raise ValueError("发布清单必须使用HTTPS")
    with urllib.request.urlopen(url, timeout=20) as response:
        if urlsplit(response.url).scheme != "https":
            raise ValueError("拒绝降级重定向")
        data = json.loads(response.read(1024 * 1024))
    Version(data["version"])
    if urlsplit(data["wheel_url"]).scheme != "https" or len(data["sha256"]) != 64:
        raise ValueError("发布清单无效")
    return data


def install_release(root: Path, manifest: dict) -> Path:
    from mvs.management.lock import InstanceLock

    lock = InstanceLock(root)
    lock.acquire()
    try:
        directory = root / "releases"
        directory.mkdir(exist_ok=True)
        name = Path(urlsplit(manifest["wheel_url"]).path).name
        if not name.endswith(".whl") or not name.startswith("mcp_virtual_shell-"):
            raise ValueError("安装包名称不受支持")
        target = directory / name
        with urllib.request.urlopen(manifest["wheel_url"], timeout=60) as response:
            if urlsplit(response.url).scheme != "https":
                raise ValueError("拒绝降级重定向")
            data = response.read(64 * 1024 * 1024 + 1)
        if len(data) > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != manifest["sha256"]:
            raise ValueError("安装包大小或哈希校验失败")
        target.write_bytes(data)
        uv = shutil.which("uv")
        if not uv:
            raise ValueError("未找到uv")
        if os.environ.get("MVS_DEFER_UPDATE") == "1":
            queue_update(root, target, uv)
            return target
        subprocess.run([uv, "tool", "install", "--force", str(target) + "[console]"], check=True)
        history_path = directory / "history.json"
        history = json.loads(history_path.read_text()) if history_path.exists() else []
        history.append(str(target))
        history_path.write_text(json.dumps(history), encoding="utf-8")
        return target
    finally:
        lock.release()


def rollback_release(root: Path) -> None:
    from mvs.management.lock import InstanceLock

    lock = InstanceLock(root)
    lock.acquire()
    try:
        _rollback_release(root)
    finally:
        lock.release()


def _rollback_release(root: Path) -> None:
    history = json.loads((root / "releases/history.json").read_text())
    if len(history) < 2:
        raise ValueError("没有保留的上一个安装包")
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("未找到uv")
    if os.environ.get("MVS_DEFER_UPDATE") == "1":
        queue_update(root, Path(history[-2]), uv)
    else:
        subprocess.run([uv, "tool", "install", "--force", history[-2] + "[console]"], check=True)


def queue_update(root: Path, wheel: Path, uv: str) -> None:
    directory = root / "releases"
    directory.mkdir(exist_ok=True)
    worker = directory / "update_worker.py"
    worker.write_bytes(Path(__file__).with_name("update_worker.py").read_bytes())
    job = directory / "update-job.json"
    job.write_text(json.dumps({"parent_pid": os.getpid(), "wheel": str(wheel.resolve()), "uv": uv}))
    (directory / "update-status.json").write_text(
        json.dumps({"status": "queued", "created": time.time()})
    )
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000 | 0x00000008
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(
        [getattr(sys, "_base_executable", sys.executable), str(worker), str(job)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )
