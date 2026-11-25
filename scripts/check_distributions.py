"""验证当前版本wheel/sdist的元数据、前端、许可和文件范围。"""

import argparse
import email
import json
import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from scripts.check_repository import SECRET_PATTERNS

FORBIDDEN = {".git", ".tools", ".venv", ".mvs", "node_modules", "__pycache__", "artifacts", "dist"}
URL = "https://github.com/TheNorthS/MVS"


def inspect_members(entries: dict[str, bytes], version: str, wheel: bool) -> dict:
    metadata_name = f"mcp_virtual_shell-{version}.dist-info/METADATA" if wheel else "PKG-INFO"
    for name, body in entries.items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or set(path.parts) & FORBIDDEN:
            raise ValueError(f"分发包包含不允许的路径：{name}")
        if path.suffix in {".sqlite", ".sqlite3", ".db", ".pyc", ".mvsb"}:
            raise ValueError(f"分发包包含运行数据：{name}")
        if path.name in {".env", ".pypirc", "vault.key", "admin-token"}:
            raise ValueError(f"分发包包含私有配置：{name}")
        if any(pattern.search(body) for pattern in SECRET_PATTERNS.values()):
            raise ValueError(f"分发文件疑似包含凭据：{name}")
    metadata = email.message_from_bytes(entries[metadata_name])
    if metadata["Name"] != "mcp-virtual-shell" or metadata["Version"] != version:
        raise ValueError("分发包名称或版本不匹配")
    if metadata["License-Expression"] != "MIT":
        raise ValueError("分发包缺少MIT许可元数据")
    if not any(URL in value for value in metadata.get_all("Project-URL", [])):
        raise ValueError("分发包缺少正确的仓库地址")
    if metadata["Description-Content-Type"] != "text/markdown":
        raise ValueError("分发说明必须为Markdown")
    readme = metadata.get_payload()
    if re.search(r"\]\((?!https://|#)[^)]+\)", readme):
        raise ValueError("PyPI说明包含不能解析的相对链接")
    web = "mvs/web/" if wheel else "src/mvs/web/"
    required = {web + "index.html", web + "licenses/shadcn-ui.txt"}
    license_prefix = f"mcp_virtual_shell-{version}.dist-info/licenses/" if wheel else ""
    required |= {license_prefix + "LICENSE", license_prefix + "NOTICE"}
    if not required <= entries.keys():
        raise ValueError(f"分发包缺少必要文件：{sorted(required - entries.keys())}")
    for asset in re.findall(r'(?:src|href)="(/[^"]+)"', entries[web + "index.html"].decode()):
        if web + asset.lstrip("/") not in entries:
            raise ValueError("页面引用了未打包的资源：" + asset)
    return {"type": "wheel" if wheel else "sdist", "version": version, "files": len(entries)}


def inspect_distribution(path: Path, version: str) -> dict:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            entries = {
                name: archive.read(name) for name in archive.namelist() if not name.endswith("/")
            }
        return inspect_members(entries, version, True)
    with tarfile.open(path, "r:gz") as archive:
        prefix = f"mcp_virtual_shell-{version}/"
        entries = {}
        for member in archive.getmembers():
            if not member.name.startswith(prefix) or member.issym() or member.islnk():
                raise ValueError("源码包包含异常路径或链接")
            if member.isfile():
                stream = archive.extractfile(member)
                assert stream is not None
                entries[member.name.removeprefix(prefix)] = stream.read()
    return inspect_members(entries, version, False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version", default="0.0.1")
    args = parser.parse_args()
    paths = [
        args.directory / f"mcp_virtual_shell-{args.version}-py3-none-any.whl",
        args.directory / f"mcp_virtual_shell-{args.version}.tar.gz",
    ]
    actual = {p.name for p in args.directory.iterdir() if p.name != ".gitignore"}
    if actual != {p.name for p in paths}:
        raise SystemExit("PyPI目录必须恰好包含当前版本的一个wheel和一个sdist")
    print(json.dumps([inspect_distribution(p, args.version) for p in paths], ensure_ascii=False))


if __name__ == "__main__":
    main()
