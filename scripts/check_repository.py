"""检查Git待提交文件；只输出风险类型和位置，不打印疑似凭据内容。"""

import json
import re
import subprocess
from pathlib import Path, PurePosixPath

SECRET_PATTERNS = {
    "API密钥": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    "GitHub令牌": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "私钥": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
PRIVATE_PARTS = {".git", ".tools", ".venv", ".mvs", "node_modules", "__pycache__", "dist", "build"}
PRIVATE_NAMES = {".pypirc", "admin-token", "vault.key"}


def source_files(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    )
    names = sorted(set(output.decode("utf-8").split("\0")) - {""})
    return [root / name for name in names if (root / name).is_file()]


def inspect_paths(root: Path, paths: list[Path]) -> list[dict]:
    findings = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        parts = PurePosixPath(relative).parts
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            findings.append({"file": relative, "reason": "链接或路径越界"})
            continue
        if (
            set(parts) & PRIVATE_PARTS
            or path.name in PRIVATE_NAMES
            or (path.name.startswith(".env") and not path.name.endswith(".example"))
            or path.suffix in {".sqlite", ".sqlite3", ".db", ".mvsb", ".pyc"}
        ):
            findings.append({"file": relative, "reason": "运行数据或私有配置"})
        if path.stat().st_size > 50 * 1024 * 1024:
            findings.append({"file": relative, "reason": "单文件超过50MiB"})
            continue
        body = path.read_bytes()
        for label, pattern in SECRET_PATTERNS.items():
            match = pattern.search(body)
            if match:
                findings.append(
                    {
                        "file": relative,
                        "line": body[: match.start()].count(b"\n") + 1,
                        "reason": label,
                    }
                )
    return findings


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = source_files(root)
    findings = inspect_paths(root, paths)
    print(
        json.dumps(
            {
                "files": len(paths),
                "bytes": sum(p.stat().st_size for p in paths),
                "findings": findings,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
