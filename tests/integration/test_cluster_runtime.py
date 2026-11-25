import asyncio
import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("MVS_TEST_REDIS_URL") and os.environ.get("MVS_TEST_POSTGRES_DSN")),
    reason="需要真实Redis/PostgreSQL集群测试实例",
)


async def test_node_refresh_reads_latest_revision_after_waiting(
    tmp_path, monkeypatch, postgres_dsn
):
    from cryptography.fernet import Fernet

    from mvs.management.runtime import ManagedRuntime
    from mvs.management.store import StateStore

    monkeypatch.setenv("MVS_CONTROL_POSTGRES_DSN", postgres_dsn)
    monkeypatch.setenv("MVS_VAULT_KEY", Fernet.generate_key().decode())
    store = StateStore(tmp_path)
    store.initialize()
    runtime = ManagedRuntime(store)
    await runtime.start()
    try:
        revision, state = store.read()
        state["users"][0]["rate_limit"] = 100
        revision = store.save(revision, state)
        async with runtime.gate:
            waiting = asyncio.create_task(runtime.synchronize())
            await asyncio.sleep(0)  # 该节点已读到上一版，正在等待本地在途请求退出。
            state["users"][0]["rate_limit"] = 200
            latest = store.save(revision, state)
        await waiting
        assert runtime.generation == latest
        assert runtime.current_state["users"][0]["rate_limit"] == 200
    finally:
        await runtime.close()
        store.close()


async def test_two_nodes_sessions_results_permissions_and_token_revocation(
    tmp_path, monkeypatch, postgres_dsn
):
    from cryptography.fernet import Fernet

    from mvs.management.app import create_console
    from mvs.management.store import StateStore

    monkeypatch.setenv("MVS_CONTROL_POSTGRES_DSN", postgres_dsn)
    monkeypatch.setenv("MVS_POSTGRES_DSN", postgres_dsn)
    monkeypatch.setenv("MVS_REDIS_URL", os.environ["MVS_TEST_REDIS_URL"])
    monkeypatch.setenv("MVS_VAULT_KEY", Fernet.generate_key().decode())
    left, right = tmp_path / "a", tmp_path / "b"
    store = StateStore(left)
    admin_token = store.initialize()
    store.close()
    app_a, app_b = create_console(left), create_console(right)
    async with app_a.router.lifespan_context(app_a), app_b.router.lifespan_context(app_b):
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app_a),
                base_url="http://localhost",
                headers={"Authorization": "Bearer " + admin_token},
            ) as a,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app_b),
                base_url="http://localhost",
                headers={"Authorization": "Bearer " + admin_token},
            ) as b,
        ):
            user = (
                await a.put(
                    "/api/admin/users/reader",
                    json={"revision": 1, "value": {"servers": ["demo"], "rate_limit": 1000}},
                )
            ).json()
            token = user["issued_token"]
            headers = {"Authorization": "Bearer " + token}
            sid = (await a.post("/api/v1/sessions", json={}, headers=headers)).json()["session_id"]
            await a.post(
                "/api/v1/shell/execute",
                headers=headers,
                json={"session_id": sid, "command": "cd /mcp/demo/tools"},
            )

            async def call(c):
                result = await c.post(
                    "/api/v1/shell/execute",
                    headers=headers,
                    json={"session_id": sid, "command": "run add --a 3 --b 8"},
                )
                return result.json()

            results = await asyncio.gather(*(call(a if n % 2 == 0 else b) for n in range(20)))
            assert all(r["data"] == {"result": 11} for r in results), results
            assert len({r["request_id"] for r in results}) == 20
            ref = results[0]["result_ref"]
            saved = (
                await b.post(
                    "/api/v1/shell/execute",
                    headers=headers,
                    json={"session_id": sid, "command": f"cat {ref}"},
                )
            ).json()
            assert saved["data"] == {"result": 11}, saved
            state = (await a.get("/api/admin/state")).json()
            assert (
                await a.put(
                    "/api/admin/users/reader",
                    json={"revision": state["revision"], "value": {"servers": []}},
                )
            ).status_code == 200
            denied = await b.post(
                "/api/v1/shell/execute",
                headers=headers,
                json={"session_id": sid, "command": "/mcp/demo/tools/add --a 3 --b 8"},
            )
            assert denied.json()["error"]["code"] == "NOT_FOUND", denied.text
            rev = (await a.get("/api/admin/state")).json()["revision"]
            assert (
                await a.post("/api/admin/users/reader/rotate", json={"revision": rev})
            ).status_code == 200
            assert (await b.post("/api/v1/sessions", json={}, headers=headers)).status_code == 401
