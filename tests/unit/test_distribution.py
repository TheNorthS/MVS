import pytest

from scripts.check_distributions import inspect_members
from scripts.check_repository import inspect_paths


def package_entries():
    prefix = "mcp_virtual_shell-0.0.1.dist-info/"
    return {
        prefix + "METADATA": (
            b"Metadata-Version: 2.4\nName: mcp-virtual-shell\nVersion: 0.0.1\n"
            b"License-Expression: MIT\nProject-URL: Repository, https://github.com/TheNorthS/MVS\n"
            b"Description-Content-Type: text/markdown\n\n# MVS\n"
        ),
        prefix + "licenses/LICENSE": b"MIT License",
        prefix + "licenses/NOTICE": b"MVS",
        "mvs/web/index.html": b'<script src="/assets/app.js"></script>',
        "mvs/web/assets/app.js": b"console.log('MVS')",
        "mvs/web/licenses/shadcn-ui.txt": b"MIT License",
    }


def test_distribution_includes_resolvable_ui_and_license():
    entries = package_entries()
    assert inspect_members(entries, "0.0.1", True)["version"] == "0.0.1"
    del entries["mvs/web/assets/app.js"]
    with pytest.raises(ValueError, match="未打包"):
        inspect_members(entries, "0.0.1", True)


@pytest.mark.parametrize(
    "name", [".tools/private.json", "mvs/control.sqlite3", "mvs/.env", "../escape"]
)
def test_distribution_rejects_private_files(name):
    with pytest.raises(ValueError):
        inspect_members({**package_entries(), name: b"private"}, "0.0.1", True)


def test_repository_secret_scan_reports_position_without_value(tmp_path):
    path = tmp_path / "config.py"
    secret = b"sk-" + b"a" * 32
    path.write_bytes(b"# config\nkey=" + secret)
    findings = inspect_paths(tmp_path, [path])
    assert findings == [{"file": "config.py", "line": 2, "reason": "API密钥"}]
    assert secret.decode() not in repr(findings)
