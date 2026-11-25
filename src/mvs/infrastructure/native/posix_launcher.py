"""独立进程中设置资源限制后替换为目标程序，避免在线程进程里使用preexec_fn。"""

import importlib
import os
import signal
import subprocess
import sys
import time
from typing import Any


def darwin_supervise(argv: list[str], memory_mb: int) -> int:
    """macOS不支持RLIMIT_AS；按50ms间隔监测同一进程组的RSS总量。"""
    if sys.platform == "win32":
        raise OSError("POSIX进程组监测不能在Windows运行")
    # 调用方通过start_new_session创建独立组，禁止误伤启动器所在的用户Shell。
    if os.getpgrp() != os.getpid():
        os.setsid()
    group = os.getpgrp()
    child = subprocess.Popen(argv, env=dict(os.environ))
    try:
        while child.poll() is None:
            snapshot = subprocess.run(
                ["/bin/ps", "-axo", "pgid=,rss="],
                capture_output=True,
                text=True,
                timeout=1,
                check=True,
            )
            resident_kb = 0
            for line in snapshot.stdout.splitlines():
                fields = line.split()
                if len(fields) == 2 and int(fields[0]) == group:
                    resident_kb += int(fields[1])
            if resident_kb > memory_mb * 1024:
                os.killpg(group, signal.SIGKILL)
            time.sleep(0.05)
        return child.returncode
    finally:
        if child.poll() is None:
            # 监控自身失败也不能放任受限任务继续执行。
            os.killpg(group, signal.SIGKILL)


def main() -> None:
    if sys.platform == "win32":
        raise SystemExit("POSIX启动器不能在Windows运行")
    resource: Any = importlib.import_module("resource")
    memory, cpu = int(sys.argv[1]), int(sys.argv[2])
    if memory and sys.platform != "darwin":
        resource.setrlimit(resource.RLIMIT_AS, (memory * 1024 * 1024, memory * 1024 * 1024))
    if cpu:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if memory and sys.platform == "darwin":
        code = darwin_supervise(sys.argv[3:], memory)
        raise SystemExit(code if code >= 0 else 128 - code)
    os.execve(sys.argv[3], sys.argv[3:], dict(os.environ))


if __name__ == "__main__":
    main()
