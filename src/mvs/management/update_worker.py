"""在调用方退出后替换其uv工具环境，避免Windows锁定mvs.exe。"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def wait_parent(pid: int) -> None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32")
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if handle:
            kernel.WaitForSingleObject(handle, 60000)
            kernel.CloseHandle(handle)
    else:
        for _ in range(600):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)


def main() -> None:
    path = Path(sys.argv[1])
    job = json.loads(path.read_text())
    wait_parent(job["parent_pid"])
    result = subprocess.run(
        [job["uv"], "tool", "install", "--force", job["wheel"] + "[console]"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    status = {
        "status": "complete" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "wheel": Path(job["wheel"]).name,
        "completed": time.time(),
    }
    if result.returncode == 0:
        history_path = path.parent / "history.json"
        history = json.loads(history_path.read_text()) if history_path.exists() else []
        history.append(job["wheel"])
        history_path.write_text(json.dumps(history))
    (path.parent / "update-status.json").write_text(json.dumps(status), encoding="utf-8")


if __name__ == "__main__":
    main()
