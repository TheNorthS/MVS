import argparse

from mvs.management.commands import handle
from mvs.management.store import StateStore


def test_init_import_export_reset_and_doctor(tmp_path, capsys):
    def run(mode, **values):
        return handle(argparse.Namespace(mode=mode, home=str(tmp_path / "instance"), **values))

    assert run("init", empty=True) == 0
    store = StateStore(tmp_path / "instance")
    original = (tmp_path / "instance/admin-token").read_text()
    assert len(store.read()[1]["servers"]) == 0
    store.close()
    assert run("init", empty=False) == 0
    assert (tmp_path / "instance/admin-token").read_text() == original
    assert run("config", action="import", path="configs/servers.example.yaml") == 0
    exported = tmp_path / "export.yaml"
    assert run("config", action="export", path=str(exported)) == 0
    assert "demo" in exported.read_text()
    assert original not in exported.read_text()
    assert run("token", action="reset", user="admin") == 0
    new = (tmp_path / "instance/admin-token").read_text()
    assert new != original
    store = StateStore(tmp_path / "instance")
    assert store.authenticate(original) is None
    assert store.authenticate(new)["id"] == "admin"
    store.close()
    run("doctor")
    assert "initialized" in capsys.readouterr().out
