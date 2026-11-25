"""在构建机器生成包含前端资源的wheel与最终用户安装包。"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from project_metadata import checked_version
from release_bundle import build_bundle

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument(
    "--skip-install", action="store_true", help="复用已经npm ci安装的依赖，仍执行前端构建"
)
parser.add_argument("--output", type=Path, help="输出目录，默认dist/release/当前版本")
options = parser.parse_args()
version = checked_version(root)
output = (options.output or root / "dist/release" / version).resolve()
pypi_dir, installer_dir = output / "pypi", output / "installers"
if output == root or not output.is_relative_to(root / "dist"):
    raise SystemExit("发布输出必须放在项目dist目录内")
pypi_dir.mkdir(parents=True, exist_ok=True)
installer_dir.mkdir(parents=True, exist_ok=True)
npm = shutil.which("npm.cmd") or shutil.which("npm")
uv = shutil.which("uv") or str(root / ".tools/bin/uv.exe")
if not npm:
    raise SystemExit("构建机器需要Node/npm，最终用户无需安装Node。")
subprocess.run([sys.executable, "scripts/check_repository.py"], cwd=root, check=True)
if not options.skip_install:
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=root / "web", check=True)
subprocess.run([npm, "run", "build"], cwd=root / "web", check=True)
subprocess.run([uv, "build", "--out-dir", str(pypi_dir)], cwd=root, check=True)
wheel = pypi_dir / f"mcp_virtual_shell-{version}-py3-none-any.whl"
if not wheel.is_file():
    raise SystemExit(f"构建未产生预期版本的wheel：{wheel.name}")
subprocess.run(
    [sys.executable, "-m", "scripts.check_distributions", str(pypi_dir), "--version", version],
    cwd=root,
    check=True,
)
archive = build_bundle(root, wheel, output_dir=installer_dir)
if os.environ.get("MVS_RELEASE_BASE_URL"):
    manifest = {
        "version": wheel.name.split("-")[1],
        "wheel_url": os.environ["MVS_RELEASE_BASE_URL"].rstrip("/") + "/" + wheel.name,
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }
    (installer_dir / "latest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
checksums = {
    p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(output.rglob("*"))
    if p.is_file() and p.name not in {"SHA256SUMS.json", ".gitignore"}
}
(output / "SHA256SUMS.json").write_text(json.dumps(checksums, indent=2), encoding="utf-8")
print(f"PyPI包：{pypi_dir}\n安装包：{archive}\n构建完成；本命令不上传或发布。")
