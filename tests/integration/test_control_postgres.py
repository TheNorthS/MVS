import os

import pytest


@pytest.mark.skipif(
    not os.environ.get("MVS_TEST_POSTGRES_DSN"), reason="需要真实PostgreSQL控制面测试实例"
)
async def test_shared_control_state_revisions(monkeypatch, tmp_path, postgres_dsn):
    from cryptography.fernet import Fernet

    from mvs.management.store import StateStore

    monkeypatch.setenv("MVS_CONTROL_POSTGRES_DSN", postgres_dsn)
    monkeypatch.setenv("MVS_VAULT_KEY", Fernet.generate_key().decode())
    one, two = StateStore(tmp_path / "one"), StateStore(tmp_path / "two")
    try:
        one.initialize()
        revision, state = one.read()
        state["secrets"]["MVS_SECRET_SHARED"] = "shared-secret"
        one.save(revision, state)
        assert two.read()[0] == revision + 1
        assert two.read()[1]["secrets"]["MVS_SECRET_SHARED"] == "shared-secret"
        with pytest.raises(ValueError):
            two.save(revision, state)
    finally:
        one.close()
        two.close()
