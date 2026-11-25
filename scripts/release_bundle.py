"""生成安装ZIP，确保中文PowerShell脚本可由Windows PowerShell 5.1解析。"""

import hashlib
import json
import os
import zipfile
from pathlib import Path


def build_bundle(root: Path, wheel: Path, output_dir: Path | None = None) -> Path:
    with zipfile.ZipFile(wheel) as package:
        if "mvs/web/index.html" not in package.namelist():
            raise ValueError("wheel没有包含管理后台")
    output_dir = output_dir or wheel.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{wheel.name.split('-')[0]}-{wheel.name.split('-')[1]}-installer.zip"
    temporary = archive.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(wheel, wheel.name)
            for source in (
                "scripts/install.sh",
                "scripts/install.ps1",
                "scripts/installer_gui.py",
                "docs/guides/user_installation.md",
                "web/public/licenses/shadcn-ui.txt",
            ):
                if source.endswith(".ps1"):
                    # 5.1无BOM时按ANSI读取；在所有构建操作系统上显式输出UTF-8 BOM。
                    body = (root / source).read_text(encoding="utf-8-sig")
                    bundle.writestr(source, body.encode("utf-8-sig"))
                else:
                    bundle.write(root / source, source)
            for source in ("LICENSE", "NOTICE", "docs/PYPI.md"):
                if (root / source).is_file():
                    bundle.write(root / source, source)
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel, archive)}
    if output_dir == wheel.parent:
        (wheel.parent / "SHA256SUMS.json").write_text(
            json.dumps(checksums, indent=2), encoding="utf-8"
        )
    return archive
