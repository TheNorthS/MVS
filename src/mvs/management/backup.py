"""完整实例备份和离线恢复；加密备份可跨机器恢复，拒绝路径穿越。"""

import base64
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from mvs.management.lock import InstanceLock


def backup(root: Path, destination: Path, password: str, lock_instance: bool = True) -> None:
    if len(password) < 12:
        raise ValueError("备份密码至少12字符")
    if destination.exists():
        raise ValueError("备份文件已存在")
    if destination.resolve().is_relative_to(root.resolve()):
        raise ValueError("备份文件不能写入被备份的实例目录内部")
    lock = InstanceLock(root)
    if lock_instance:
        lock.acquire()
    try:
        buffer = io.BytesIO()
        hashes = {}
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in root.rglob("*"):
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or path.name == "serve.lock"
                    or path.name.endswith(("-wal", "-shm", "-journal"))
                ):
                    continue
                if path.suffix in {".sqlite3", ".sqlite"}:
                    with tempfile.TemporaryDirectory() as tmp:
                        target = Path(tmp) / "snapshot.sqlite"
                        with (
                            closing(sqlite3.connect(path)) as source,
                            closing(sqlite3.connect(target)) as dest,
                        ):
                            source.backup(dest)
                        data = target.read_bytes()
                else:
                    data = path.read_bytes()
                name = path.relative_to(root).as_posix()
                hashes[name] = hashlib.sha256(data).hexdigest()
                archive.writestr(name, data)
            archive.writestr("backup-manifest.json", json.dumps({"format": 1, "files": hashes}))
        salt = os.urandom(16)
        key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode())
        destination.write_bytes(
            b"MVSB1" + salt + Fernet(base64.urlsafe_b64encode(key)).encrypt(buffer.getvalue())
        )
        if os.name != "nt":
            destination.chmod(0o600)
    finally:
        if lock_instance:
            lock.release()


def restore(source: Path, destination: Path, password: str) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("恢复目标必须不存在或为空目录")
    raw = source.read_bytes()
    if len(raw) > 512 * 1024 * 1024:
        raise ValueError("备份文件超过512MiB限制")
    if raw[:5] != b"MVSB1":
        raise ValueError("不支持的备份格式")
    key = Scrypt(salt=raw[5:21], length=32, n=2**15, r=8, p=1).derive(password.encode())
    try:
        data = Fernet(base64.urlsafe_b64encode(key)).decrypt(raw[21:])
    except Exception:
        raise ValueError("备份密码错误或文件损坏") from None
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read("backup-manifest.json"))
        if sum(info.file_size for info in archive.infolist()) > 1024 * 1024 * 1024:
            raise ValueError("备份解压大小超过1GiB限制")
        files = {}
        for name, digest in manifest["files"].items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
                raise ValueError("备份包含非法路径")
            value = archive.read(name)
            if hashlib.sha256(value).hexdigest() != digest:
                raise ValueError("备份哈希不匹配")
            files[name] = value
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, value in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(value)
        if os.name != "nt":
            target.chmod(0o600)
