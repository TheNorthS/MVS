"""在当前OS/架构制作携带uv、独立Python和全部依赖wheel的离线发行目录。"""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("wheel")
parser.add_argument("--output", default="dist/offline-full")
args = parser.parse_args()
output = Path(args.output).resolve()
if output.exists():
    raise SystemExit("输出目录已存在，拒绝覆盖")
output.mkdir(parents=True)
uv = shutil.which("uv")
if not uv:
    raise SystemExit("需要uv构建离线发行包")
subprocess.run([uv, "python", "install", "3.12"], check=True)
python = Path(
    subprocess.check_output([uv, "python", "find", "--managed-python", "3.12"], text=True).strip()
)
python_root = python.parent if sys.platform == "win32" else python.parent.parent
shutil.copytree(
    python_root,
    output / "python",
    symlinks=False,
    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
)
shutil.copyfile(uv, output / ("uv.exe" if sys.platform == "win32" else "uv"))
if sys.platform != "win32":
    (output / "uv").chmod(0o755)
wheel = Path(args.wheel).resolve()
shutil.copyfile(wheel, output / wheel.name)
subprocess.run(
    [
        uv,
        "run",
        "--isolated",
        "--with",
        "pip",
        "python",
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "--dest",
        str(output / "wheels"),
        str(wheel) + "[console]",
    ],
    check=True,
)
installer = Path(__file__).resolve().parent / "offline_install.py"
shutil.copyfile(installer, output / "install.py")
shutil.copyfile(Path(__file__).with_name("installer_gui.py"), output / "installer_gui.py")
(output / "install-gui.cmd").write_text(
    '@echo off\r\n"%~dp0python\\python.exe" -B "%~dp0installer_gui.py"\r\n', encoding="ascii"
)
(output / "install.cmd").write_text(
    '@echo off\r\n"%~dp0python\\python.exe" -B "%~dp0install.py" %*\r\n', encoding="ascii"
)
(output / "install.sh").write_text(
    '#!/bin/sh\nset -eu\nbase=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
    'exec "$base/python/bin/python3" -B "$base/install.py" "$@"\n',
    encoding="ascii",
)
manifest = {
    "platform": sys.platform,
    "machine": platform.machine().lower().replace("amd64", "x86_64").replace("aarch64", "arm64"),
    "files": {
        p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in output.rglob("*")
        if p.is_file()
    },
}
(output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
archive = output.parent / (output.name + ".zip")
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for p in output.rglob("*"):
        if p.is_file():
            z.write(p, p.relative_to(output))
print(archive)
