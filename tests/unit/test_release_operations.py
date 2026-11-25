import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mvs.infrastructure.storage.rate_limit import RateLimiter
from mvs.infrastructure.storage.result_store import ResultStore
from mvs.management.service_install import install_service
from mvs.management.updates import check_release, install_release, rollback_release


class Response(io.BytesIO):
    url = "https://releases.example/file"


def test_upgrade_hash_and_rollback(tmp_path, monkeypatch):
    payload = b"wheel-bytes"
    manifest = {
        "version": "0.0.1",
        "wheel_url": "https://releases.example/mcp_virtual_shell-0.0.1-py3-none-any.whl",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    with patch("urllib.request.urlopen", return_value=Response(json.dumps(manifest).encode())):
        assert check_release("https://releases.example/latest.json") == manifest
    with (
        patch("urllib.request.urlopen", side_effect=lambda *a, **k: Response(payload)),
        patch("shutil.which", return_value="uv"),
        patch("subprocess.run") as run,
    ):
        install_release(tmp_path, manifest)
        second = {**manifest, "wheel_url": manifest["wheel_url"].replace("0.0.1", "0.0.2")}
        install_release(tmp_path, second)
        rollback_release(tmp_path)
        assert run.call_args.args[0][-1].endswith("0.0.1-py3-none-any.whl[console]")
    with patch("urllib.request.urlopen", return_value=Response(b"corrupt")):
        with pytest.raises(ValueError, match="哈希"):
            install_release(tmp_path, manifest)


def test_sqlite_limiter_shared_and_orphan_repair(tmp_path):
    one, two = RateLimiter(tmp_path / "rate.db"), RateLimiter(tmp_path / "rate.db")
    assert one.allow("t", "u", 2) and two.allow("t", "u", 2)
    assert not one.allow("t", "u", 2)
    assert one.allow("other", "u", 2)
    one.close()
    two.close()
    store = ResultStore(tmp_path / "results")
    orphan = store.objects / "orphan"
    orphan.write_text("abandoned")
    assert store.repair()["removed_orphans"] == 1
    assert not orphan.exists()
    store.close()


def test_service_definition_no_shell_interpolation(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch("shutil.which", return_value="/opt/mvs/bin/mvs"), patch("subprocess.run") as run:
        install_service(tmp_path / "data space")
        body = (tmp_path / ".config/systemd/user/mvs.service").read_text()
        assert '"/opt/mvs/bin/mvs" serve --home' in body
        assert run.call_args.args[0] == ["systemctl", "--user", "enable", "--now", "mvs.service"]
