import asyncio
import multiprocessing
import os
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("MVS_TEST_REDIS_URL") and os.environ.get("MVS_TEST_POSTGRES_DSN")),
    reason="需要真实Redis/PostgreSQL集群测试实例",
)


def serve_node(root, port, stop):
    """独立进程运行真实HTTP服务，通过父进程事件触发正常关闭。"""
    import uvicorn

    from mvs.management.app import create_console

    async def main():
        server = uvicorn.Server(
            uvicorn.Config(
                create_console(Path(root)),
                host="127.0.0.1",
                port=port,
                log_level="error",
                access_log=False,
                loop="asyncio",
            )
        )

        async def monitor():
            while not stop.is_set():  # noqa: ASYNC110
                await asyncio.sleep(0.05)
            server.should_exit = True

        watcher = asyncio.create_task(monitor())
        try:
            await server.serve()
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    asyncio.run(main())


@asynccontextmanager
async def node(root, token):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    context = multiprocessing.get_context("spawn")
    stop = context.Event()
    process = context.Process(target=serve_node, args=(str(root), port, stop))
    process.start()
    try:
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            timeout=40,
            headers={"Authorization": "Bearer " + token},
        ) as client:
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                assert process.is_alive(), "真实HTTP节点未能启动"
                try:
                    ready = await client.get("/api/v1/health/live", timeout=2)
                    if ready.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.1)
            else:
                pytest.fail("真实HTTP节点未在40秒内就绪")
            yield client
    finally:
        stop.set()
        await asyncio.to_thread(process.join, 15)
        if process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join, 5)
        exitcode = process.exitcode
        process.close()
        assert exitcode == 0, "真实HTTP节点未正常关闭"


async def test_two_process_nodes_share_session_after_restart(tmp_path, monkeypatch, postgres_dsn):
    from cryptography.fernet import Fernet

    from mvs.management.store import StateStore

    monkeypatch.setenv("MVS_CONTROL_POSTGRES_DSN", postgres_dsn)
    monkeypatch.setenv("MVS_POSTGRES_DSN", postgres_dsn)
    monkeypatch.setenv("MVS_REDIS_URL", os.environ["MVS_TEST_REDIS_URL"])
    monkeypatch.setenv("MVS_VAULT_KEY", Fernet.generate_key().decode())
    left, right = tmp_path / "a", tmp_path / "b"
    store = StateStore(left)
    admin = store.initialize()
    store.close()
    async with node(right, admin) as b:
        async with node(left, admin) as a:
            user = await a.put(
                "/api/admin/users/reader",
                json={
                    "revision": 1,
                    "value": {"servers": ["demo"], "rate_limit": 1000},
                },
            )
            assert user.status_code == 200, user.text
            headers = {"Authorization": "Bearer " + user.json()["issued_token"]}
            session = (await a.post("/api/v1/sessions", json={}, headers=headers)).json()[
                "session_id"
            ]

            async def execute(client, command):
                response = await client.post(
                    "/api/v1/shell/execute",
                    headers=headers,
                    json={"session_id": session, "command": command},
                )
                assert response.status_code == 200, response.text
                return response.json()

            assert (await execute(a, "cd /mcp/demo/tools"))["status"] == "success"
            results = await asyncio.gather(
                *(execute(a if n % 2 == 0 else b, "run add --a 3 --b 8") for n in range(20))
            )
            assert all(r["data"] == {"result": 11} for r in results), results
            assert len({r["request_id"] for r in results}) == 20
        # A进程退出后，B继续读取A生成的结果，并保持相同session与cwd。
        assert (await execute(b, "cat " + results[0]["result_ref"]))["data"] == {"result": 11}
        async with node(left, admin) as restarted:
            assert (await execute(restarted, "run add --a 1 --b 4"))["data"] == {"result": 5}
            rev = (await b.get("/api/admin/state")).json()["revision"]
            assert (
                await b.put(
                    "/api/admin/users/reader",
                    json={
                        "revision": rev,
                        "value": {"servers": []},
                    },
                )
            ).status_code == 200
            assert (await execute(restarted, "/mcp/demo/tools/add --a 1 --b 4"))["error"][
                "code"
            ] == "NOT_FOUND"
            rev = (await b.get("/api/admin/state")).json()["revision"]
            assert (
                await b.post("/api/admin/users/reader/rotate", json={"revision": rev})
            ).status_code == 200
            assert (
                await restarted.post("/api/v1/sessions", json={}, headers=headers)
            ).status_code == 401
