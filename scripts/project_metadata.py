"""校验项目版本一致性；pyproject.toml是当前版本的唯一维护入口。"""

import json
import tomllib
from pathlib import Path


def checked_version(root: Path) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    package = json.loads((root / "web/package.json").read_text(encoding="utf-8"))
    npm_lock = json.loads((root / "web/package-lock.json").read_text(encoding="utf-8"))
    uv_lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    locked = next(p for p in uv_lock["package"] if p["name"] == project["name"])
    versions = {
        "web/package.json": package["version"],
        "web/package-lock.json": npm_lock["version"],
        "web/package-lock.json packages[空键]": npm_lock["packages"][""]["version"],
        "uv.lock": locked["version"],
    }
    for source, actual in versions.items():
        if actual != version:
            raise ValueError(f"版本不一致：{source}={actual}，pyproject.toml={version}")
    return version


if __name__ == "__main__":
    print("项目版本一致：" + checked_version(Path(__file__).resolve().parents[1]))
