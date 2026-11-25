import json

import httpx
import pytest

from mvs.management.app import create_console
from mvs.management.store import StateStore


def initialized(tmp_path):
    store = StateStore(tmp_path)
    token = store.initialize()
    assert store.initialize() is None
    assert token not in json.dumps(store.read())
    store.close()
    return token


async def test_admin_lifecycle_reload_acl_and_redaction(tmp_path):
    token = initialized(tmp_path)
    app = create_console(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://localhost"
        ) as c:
            assert (await c.get("/api/admin/state")).status_code == 401
            c.headers["Authorization"] = "Bearer " + token
            state = (await c.get("/api/admin/state")).json()
            assert "token_hash" not in json.dumps(state)
            probe = (await c.post("/api/admin/servers/demo/probe")).json()
            assert {"add", "echo"} <= {tool["name"] for tool in probe["tools"]}
            user = await c.put(
                "/api/admin/users/alice",
                json={
                    "revision": state["revision"],
                    "value": {"name": "Alice", "servers": ["demo"]},
                },
            )
            assert user.status_code == 200, user.text
            alice = user.json()["issued_token"]
            assert (
                await c.get("/api/admin/state", headers={"Authorization": "Bearer " + alice})
            ).status_code == 403
            sid = (
                await c.post(
                    "/api/v1/sessions", json={}, headers={"Authorization": "Bearer " + alice}
                )
            ).json()["session_id"]
            result = (
                await c.post(
                    "/api/v1/shell/execute",
                    headers={"Authorization": "Bearer " + alice},
                    json={"session_id": sid, "command": "/mcp/demo/tools/add --a 2 --b 3"},
                )
            ).json()
            assert result["data"] == {"result": 5}, result
            forbidden = await c.get("/api/admin/result", params={"ref": result["result_ref"]})
            assert forbidden.status_code == 404
            revision = user.json()["revision"]
            disabled = await c.put(
                "/api/admin/users/alice", json={"revision": revision, "value": {"enabled": False}}
            )
            assert disabled.status_code == 200
            assert (
                await c.post(
                    "/api/v1/sessions", json={}, headers={"Authorization": "Bearer " + alice}
                )
            ).status_code == 401
            stale = await c.put("/api/admin/users/bob", json={"revision": revision, "value": {}})
            assert stale.status_code == 409
            revision = disabled.json()["revision"]
            last_admin = await c.request(
                "DELETE", "/api/admin/users/admin", json={"revision": revision}
            )
            assert last_admin.status_code == 400
            secret = await c.put(
                "/api/admin/secrets/MVS_SECRET_TEST",
                json={"revision": revision, "value": {"secret": "sensitive-value"}},
            )
            assert secret.status_code == 200
            assert "sensitive-value" not in secret.text
            assert secret.json()["secret_names"] == ["MVS_SECRET_TEST"]
            assert "sensitive-value" not in (await c.get("/api/admin/events")).text
            assert (
                await c.put(
                    "/api/admin/model",
                    headers={"Origin": "https://evil.example"},
                    json={"revision": secret.json()["revision"], "value": {}},
                )
            ).status_code == 403


async def test_invalid_config_no_publish_and_rotation(tmp_path):
    token = initialized(tmp_path)
    app = create_console(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://localhost",
            headers={"Authorization": "Bearer " + token},
        ) as c:
            initial = (await c.get("/api/admin/state")).json()
            invalid = await c.put(
                "/api/admin/servers/new",
                json={
                    "revision": 1,
                    "value": {"id": "new", "transport": "native", "command": "/bin/sh"},
                },
            )
            assert invalid.status_code == 400
            assert (await c.get("/api/admin/state")).json()["revision"] == initial["revision"]
            rotated = (await c.post("/api/admin/users/admin/rotate", json={"revision": 1})).json()
            assert "issued_token" in rotated
            assert (await c.get("/api/admin/state")).status_code == 401
            assert (
                await c.get(
                    "/api/admin/state",
                    headers={"Authorization": "Bearer " + rotated["issued_token"]},
                )
            ).status_code == 200
            assert (
                await c.get("/api/admin/state", headers={"Host": "evil.example"})
            ).status_code == 400
    store = StateStore(tmp_path)
    assert store.authenticate(token) is None
    assert store.authenticate(rotated["issued_token"])["id"] == "admin"
    store.close()


async def test_model_task_uses_saved_config_without_exposing_secret(tmp_path, monkeypatch):
    token = initialized(tmp_path)

    class Provider:
        def __init__(self, config):
            assert config.api_key == "private-key"

        async def complete(self, *args):
            return {
                "status": "completed",
                "model": "fixture",
                "usage": {"total_tokens": 3},
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}],
            }

        async def close(self):
            return None

    monkeypatch.setattr("mvs.management.app.ResponsesProvider", Provider)
    app = create_console(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://localhost",
            headers={"Authorization": "Bearer " + token},
        ) as c:
            response = await c.put(
                "/api/admin/secrets/MVS_SECRET_MODEL",
                json={"revision": 1, "value": {"secret": "private-key"}},
            )
            assert response.status_code == 200
            response = await c.put(
                "/api/admin/model",
                json={
                    "revision": 2,
                    "value": {
                        "base_url": "https://provider.invalid/v1",
                        "model": "fixture",
                        "api_key_env": "MVS_SECRET_MODEL",
                    },
                },
            )
            assert response.status_code == 200
            assert (await c.post("/api/admin/model/test")).json()["model"] == "fixture"
            task = (await c.post("/api/admin/agent", json={"task": "你好"})).json()
            assert task["answer"] == "OK" and task["session_closed"]
            assert "private-key" not in (await c.get("/api/admin/state")).text
            assert "private-key" not in (await c.get("/api/admin/events")).text


def test_instance_lock_and_invalid_types(tmp_path):
    from mvs.management.lock import InstanceLock
    from mvs.management.store import validate_state

    token = initialized(tmp_path)
    one, two = InstanceLock(tmp_path), InstanceLock(tmp_path)
    one.acquire()
    try:
        with pytest.raises(ValueError, match="已有运行"):
            two.acquire()
    finally:
        one.release()
    two.acquire()
    two.release()
    store = StateStore(tmp_path)
    revision, state = store.read()
    state["users"][0]["enabled"] = "false"
    with pytest.raises(ValueError):
        validate_state(state)
    assert store.authenticate(token)
    store.close()
