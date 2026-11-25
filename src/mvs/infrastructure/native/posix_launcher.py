"""独立进程中设置资源限制后替换为目标程序，避免在线程进程里使用preexec_fn。"""

import importlib
import os
import sys
from typing import Any


def main() -> None:
    if sys.platform == "win32":
        raise SystemExit("POSIX启动器不能在Windows运行")
    resource: Any = importlib.import_module("resource")
    memory, cpu = int(sys.argv[1]), int(sys.argv[2])
    if memory:
        resource.setrlimit(resource.RLIMIT_AS, (memory * 1024 * 1024, memory * 1024 * 1024))
    if cpu:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.execve(sys.argv[3], sys.argv[3:], dict(os.environ))


if __name__ == "__main__":
    main()
