import httpx

from mvs.management.app import create_console
from mvs.management.store import StateStore


async def test_approval_exact_arguments_one_shot_and_preserved_session(tmp_path):
    store = StateStore(tmp_path)
    token = store.initialize()
    store.close()
    app = create_console(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://localhost",
            headers={"Authorization": "Bearer " + token},
        ) as c:
            sid = (await c.post("/api/v1/sessions", json={})).json()["session_id"]
            await c.post(
                "/api/v1/shell/execute", json={"session_id": sid, "command": "cd /mcp/demo/tools"}
            )
            state = (await c.get("/api/admin/state")).json()
            server = state["servers"][0]
            server["approval_tools"] = ["add"]
            updated = await c.put(
                "/api/admin/servers/demo", json={"revision": state["revision"], "value": server}
            )
            assert updated.status_code == 200
            pwd = (
                await c.post("/api/v1/shell/execute", json={"session_id": sid, "command": "pwd"})
            ).json()
            assert pwd["stdout"] == "/mcp/demo/tools"
            pending = (
                await c.post(
                    "/api/v1/shell/execute",
                    json={"session_id": sid, "command": "run add --a 2 --b 3"},
                )
            ).json()
            assert pending["status"] == "approval_required"
            identity = pending["error"]["approval_id"]
            details = (await c.get(f"/api/admin/approvals/{identity}")).json()
            assert details["arguments"] == {"a": 2, "b": 3}
            assert (
                await c.post(
                    f"/api/admin/approvals/{identity}/decide",
                    json={"revision": updated.json()["revision"], "value": {"approve": True}},
                )
            ).status_code == 200
            changed = (
                await c.post(
                    "/api/v1/shell/execute",
                    json={
                        "session_id": sid,
                        "command": "run add --a 8 --b 3",
                        "approval_id": identity,
                    },
                )
            ).json()
            assert changed["error"]["code"] == "POLICY_DENIED"
            request = {"session_id": sid, "command": "run add --a 2 --b 3", "approval_id": identity}
            result = (await c.post("/api/v1/shell/execute", json=request)).json()
            assert result["data"] == {"result": 5}, result
            reused = (await c.post("/api/v1/shell/execute", json=request)).json()
            assert reused["error"]["code"] == "POLICY_DENIED"
            assert len((await c.get("/api/admin/history")).json()["history"]) >= 1
