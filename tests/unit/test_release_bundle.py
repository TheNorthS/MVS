import codecs
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.project_metadata import checked_version
from scripts.release_bundle import build_bundle

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL51 = (
    Path(os.environ.get("SystemRoot", "C:/Windows"))
    / "System32/WindowsPowerShell/v1.0/powershell.exe"
)


def test_release_rejects_frontend_version_drift(tmp_path):
    import shutil

    assert checked_version(ROOT) == "0.0.1"
    for name in ("pyproject.toml", "uv.lock", "web/package.json", "web/package-lock.json"):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    package = tmp_path / "web/package.json"
    body = json.loads(package.read_text(encoding="utf-8"))
    body["version"] = "99.0.0"
    package.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="版本不一致"):
        checked_version(tmp_path)


def test_source_installer_declares_utf8():
    body = (ROOT / "scripts/install.ps1").read_bytes()
    assert body.startswith(codecs.BOM_UTF8), "Windows PowerShell 5.1读取中文需要UTF-8 BOM"
    assert "初始化失败" in body.decode("utf-8-sig")


def make_bundle(tmp_path: Path, with_bom: bool) -> tuple[Path, Path]:
    source = tmp_path / "source"
    (source / "scripts").mkdir(parents=True)
    body = (ROOT / "scripts/install.ps1").read_text(encoding="utf-8-sig")
    (source / "scripts/install.ps1").write_text(body, encoding="utf-8-sig" if with_bom else "utf-8")
    for name in (
        "scripts/install.sh",
        "scripts/installer_gui.py",
        "docs/guides/user_installation.md",
        "web/public/licenses/shadcn-ui.txt",
    ):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    wheel = tmp_path / "mcp_virtual_shell-0.0.1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as package:
        package.writestr("mvs/web/index.html", "<!doctype html>")
    return build_bundle(source, wheel), wheel


@pytest.mark.parametrize("with_bom", [False, True])
def test_bundle_normalizes_encoding_and_keeps_wheel(tmp_path, with_bom):
    archive, wheel = make_bundle(tmp_path, with_bom)
    with zipfile.ZipFile(archive) as bundle:
        script = bundle.read("scripts/install.ps1")
        assert script.startswith(codecs.BOM_UTF8)
        assert not script[len(codecs.BOM_UTF8) :].startswith(codecs.BOM_UTF8)
        assert script.decode("utf-8-sig") == (ROOT / "scripts/install.ps1").read_text(
            encoding="utf-8-sig"
        )
        assert bundle.read(wheel.name) == wheel.read_bytes()
    checksums = json.loads((tmp_path / "SHA256SUMS.json").read_text())
    for name, value in checksums.items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == value


@pytest.mark.skipif(not POWERSHELL51.exists(), reason="仅在Windows PowerShell 5.1环境执行")
def test_powershell51_parses_source_and_extracted_package(tmp_path):
    archive, _ = make_bundle(tmp_path, False)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extract("scripts/install.ps1", tmp_path / "带空格 中文目录")
    for path in (ROOT / "scripts/install.ps1", tmp_path / "带空格 中文目录/scripts/install.ps1"):
        quoted = str(path).replace("'", "''")
        command = (
            "$tokens=$null; $errors=$null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{quoted}',"
            "[ref]$tokens,[ref]$errors) | Out-Null; "
            "if($errors.Count) { $errors | ForEach-Object { $_.ErrorId }; exit 1 }; "
            "$PSVersionTable.PSVersion.ToString()"
        )
        run = subprocess.run(
            [str(POWERSHELL51), "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        assert run.stdout.strip().startswith("5.1.")
