"""单机实例锁，防止多个控制台进程同时管理同一套配置和运行时。"""

import sys
from pathlib import Path
from typing import BinaryIO


class InstanceLock:
    def __init__(self, root: Path) -> None:
        self.path = root / "serve.lock"
        self.file: BinaryIO | None = None

    def acquire(self) -> None:
        file = self.path.open("a+b")
        try:
            file.seek(0)
            if not file.read(1):
                file.write(b"0")
                file.flush()
            file.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            raise ValueError("该数据目录已有运行中的MVS实例") from None
        self.file = file

    def release(self) -> None:
        if self.file:
            self.file.close()
            self.file = None
