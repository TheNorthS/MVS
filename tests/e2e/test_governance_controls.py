import asyncio
from unittest.mock import patch

import httpx

from mvs.management.app import create_console
from mvs.management.store import StateStore


async def test_user_parameter_role_and_parallel_requests(tmp_path):
    store = StateStore(tmp_path)
    admin = store.initialize()
    store.close()
    app = create_console(tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://localhost",
            headers={"Authorization": "Bearer " + admin},
        ) as c:
            role = {
                "demo": {
                    "tools": ["add"],
                    "arguments": {
                        "add": {
                            "type": "object",
                            "properties": {"a": {"maximum": 3}},
                            "required": ["a"],
                        }
                    },
                }
            }
            response = await c.put(
                "/api/admin/roles/small_numbers", json={"revision": 1, "value": role}
            )
            assert response.status_code == 200, response.text
            response = await c.put(
                "/api/admin/users/reader",
                json={"revision": 2, "value": {"roles": ["small_numbers"], "servers": ["demo"]}},
            )
            token = response.json()["issued_token"]
            headers = {"Authorization": "Bearer " + token}
            session = (await c.post("/api/v1/sessions", json={}, headers=headers)).json()[
                "session_id"
            ]
            okay = (
                await c.post(
                    "/api/v1/shell/execute",
                    headers=headers,
                    json={"session_id": session, "command": "/mcp/demo/tools/add --a 2 --b 3"},
                )
            ).json()
            assert okay["data"] == {"result": 5}, okay
            denied = (
                await c.post(
                    "/api/v1/shell/execute",
                    headers=headers,
                    json={"session_id": session, "command": "/mcp/demo/tools/add --a 5 --b 3"},
                )
            ).json()
            assert denied["error"]["code"] == "POLICY_DENIED"
            listing = (
                await c.post(
                    "/api/v1/shell/execute",
                    headers=headers,
                    json={"session_id": session, "command": "tools demo"},
                )
            ).json()
            assert listing["data"] == ["/mcp/demo/tools/add"]

            async def one():
                sid = (await c.post("/api/v1/sessions", json={}, headers=headers)).json()[
                    "session_id"
                ]
                result = (
                    await c.post(
                        "/api/v1/shell/execute",
                        headers=headers,
                        json={"session_id": sid, "command": "pwd"},
                    )
                ).json()
                return result["status"]

            assert await asyncio.gather(*(one() for _ in range(20))) == ["success"] * 20


async def test_template_install_registers_and_history_preserves_tokens(tmp_path):
    store = StateStore(tmp_path)
    token = store.initialize()
    store.close()
    app = create_console(tmp_path)

    async def installed(*args):
        return {
            "id": "newdemo",
            "transport": "stdio",
            "command": "python",
            "args": ["-m", "mvs.infrastructure.mcp.demo_server"],
            "allowed_tools": ["add"],
        }

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://localhost",
            headers={"Authorization": "Bearer " + token},
        ) as c:
            with patch("mvs.management.app.install_template", installed):
                result = await c.post(
                    "/api/admin/templates/git/install",
                    json={"revision": 1, "value": {"server_id": "newdemo"}},
                )
            assert result.status_code == 200, result.text
            assert any(s["id"] == "newdemo" for s in result.json()["servers"])
            rollback = await c.post("/api/admin/history/1/restore", json={"revision": 2})
            assert rollback.status_code == 200
            assert [s["id"] for s in rollback.json()["servers"]] == ["demo"]
            assert (await c.get("/api/admin/state")).status_code == 200
