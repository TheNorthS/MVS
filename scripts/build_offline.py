"""在目标操作系统上下载依赖wheel，制作无需包索引的离线依赖目录。"""

import argparse
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("wheel")
parser.add_argument("--output", default="dist/offline")
args = parser.parse_args()
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)
subprocess.run(
    [
        "uv",
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
        str(output),
        args.wheel + "[console]",
    ],
    check=True,
)
print("依赖wheel已下载；离线目标还需预装Python3.12+与uv。按相同操作系统/架构构建。")
