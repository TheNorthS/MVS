"""使用发行包自带Python/uv，校验所有文件后在用户目录离线安装。"""

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text())
machine = platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
expected = manifest["machine"].lower().replace("amd64", "x86_64").replace("aarch64", "arm64")
if manifest["platform"] != sys.platform or expected != machine:
    raise SystemExit("离线包操作系统/架构不匹配")
for name, digest in manifest["files"].items():
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or ":" in name:
        raise SystemExit("离线包包含非法路径")
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
        raise SystemExit("离线包校验失败：" + name)
uv = root / ("uv.exe" if sys.platform == "win32" else "uv")
wheel = next(root.glob("*.whl"))
env = {
    **os.environ,
    "UV_OFFLINE": "true",
    "UV_NO_INDEX": "true",
    "UV_FIND_LINKS": str(root / "wheels"),
}
subprocess.run(
    [str(uv), "tool", "install", "--python", sys.executable, "--force", str(wheel) + "[console]"],
    env=env,
    check=True,
)
directory = Path(
    subprocess.check_output([str(uv), "tool", "dir", "--bin"], env=env, text=True).strip()
)
mvs = directory / ("mvs.exe" if sys.platform == "win32" else "mvs")
subprocess.run([str(mvs), "init"], env=env, check=True)
print(f"离线安装完成：{mvs} serve --open\n请保留离线包python目录，工具环境引用此解释器。")
