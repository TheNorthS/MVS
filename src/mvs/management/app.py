"""受认证的管理控制面；模型执行接口不能修改配置。"""

import asyncio
import json
import os
import secrets
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from mvs.agent import AgentError, run_agent
from mvs.benchmarks.provider import ProviderConfig, ProviderError, ResponsesProvider
from mvs.config import parse_config
from mvs.domain.errors import ShellError
from mvs.infrastructure.mcp.client_manager import ClientManager
from mvs.management.catalog import TEMPLATES, install_template
from mvs.management.lock import InstanceLock
from mvs.management.runtime import ManagedRuntime
from mvs.management.store import StateStore, token_hash
from mvs.models.providers import CompatibleProvider, RoutedProvider


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    value: dict = Field(default_factory=dict)


class AgentTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(min_length=1, max_length=8000)


def create_console(root: Path) -> FastAPI:
    store = StateStore(root)
    if not store.initialized():
        store.close()
        raise ValueError("请先运行 mvs init")
    runtime = ManagedRuntime(store)
    instance_lock = InstanceLock(root)

    async def scheduled_backup() -> None:
        from mvs.management.backup import backup

        interval = max(60, int(os.environ.get("MVS_BACKUP_INTERVAL_SECONDS", "86400")))
        while True:
            await asyncio.sleep(interval)
            try:
                directory = Path(os.environ["MVS_BACKUP_DIR"])
                await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
                async with runtime.gate:
                    await asyncio.to_thread(
                        backup,
                        root,
                        directory / f"mvs-{int(time.time())}.mvsb",
                        os.environ["MVS_BACKUP_PASSWORD"],
                        False,
                    )
                store.event({"action": "scheduled_backup", "status": "success"})
            except Exception:
                store.event({"action": "scheduled_backup", "status": "error"})

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        backup_task = None
        try:
            instance_lock.acquire()
            await runtime.start()
            if os.environ.get("MVS_BACKUP_DIR") and os.environ.get("MVS_BACKUP_PASSWORD"):
                backup_task = asyncio.create_task(scheduled_backup())
            yield
        finally:
            if backup_task:
                backup_task.cancel()
                await asyncio.gather(backup_task, return_exceptions=True)
            await runtime.close()
            store.close()
            instance_lock.release()

    app = FastAPI(title="MVS 管理控制台", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "localhost",
            "127.0.0.1",
            "[::1]",
            *[
                host.strip()
                for host in os.environ.get("MVS_ALLOWED_HOSTS", "").split(",")
                if host.strip()
            ],
        ],
    )
    app.state.store, app.state.runtime = store, runtime

    @app.middleware("http")
    async def boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail": "拒绝跨来源请求"}, status_code=403)
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 1024 * 1024:
                return JSONResponse({"detail": "请求体超限"}, status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            }
        )
        return response

    def admin(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "请输入管理员令牌")
        token = authorization[7:]
        user = store.authenticate(token)
        if user is None:
            raise HTTPException(401, "令牌无效或已撤销")
        if "admin" not in user["roles"]:
            raise HTTPException(403, "此操作需要管理员权限")
        return token

    async def apply(body: Change, token: str, state: dict) -> dict:
        try:
            await runtime.apply(body.revision, state, token)
        except (ValueError, TypeError, KeyError):
            raise HTTPException(400, "配置校验失败；请检查字段、授权与版本") from None
        return store.public()

    @app.get("/api/admin/state")
    async def state(token: Annotated[str, Depends(admin)]) -> dict:
        public = store.public()
        current_user = store.authenticate(token)
        if current_user is None:
            raise HTTPException(401, "令牌已撤销")
        public["current_user_id"] = current_user["id"]
        async with runtime.gate:
            health = {}
            for service in runtime.app.state.services.values():
                health.update(service.registry.status)
            public.update(health=health, generation=runtime.generation, platform=sys.platform)
        return public

    @app.put("/api/admin/servers/{server_id}")
    async def save_server(
        server_id: str, body: Change, token: Annotated[str, Depends(admin)]
    ) -> dict:
        if body.value.get("id") != server_id:
            raise HTTPException(400, "服务ID与路径不一致")
        _, state = store.read()
        state["servers"] = [s for s in state["servers"] if s["id"] != server_id] + [body.value]
        for user in state["users"]:
            if "admin" in user["roles"] and server_id not in user["servers"]:
                user["servers"].append(server_id)
        return await apply(body, token, state)

    @app.delete("/api/admin/servers/{server_id}")
    async def remove_server(
        server_id: str, body: Change, token: Annotated[str, Depends(admin)]
    ) -> dict:
        _, state = store.read()
        state["servers"] = [s for s in state["servers"] if s["id"] != server_id]
        for user in state["users"]:
            user["servers"] = [s for s in user["servers"] if s != server_id]
        return await apply(body, token, state)

    @app.post("/api/admin/servers/{server_id}/probe")
    async def probe(server_id: str, token: Annotated[str, Depends(admin)]) -> dict:
        async with runtime.gate:
            configs = parse_config({"servers": store.read()[1]["servers"]})
            if server_id not in configs:
                raise HTTPException(404, "服务不存在")
            if not configs[server_id].enabled:
                raise HTTPException(400, "请先启用服务再测试连接")
            manager = ClientManager({server_id: configs[server_id]})
            try:
                tools = await manager.list_tools(server_id, refresh=True)
                store.event(
                    {"action": "connection_test", "server_id": server_id, "status": "success"}
                )
                return {"status": "success", "tools": tools}
            except Exception:
                store.event(
                    {"action": "connection_test", "server_id": server_id, "status": "error"}
                )
                raise HTTPException(
                    502, "连接失败，请检查程序、目录、凭证和网络；未执行业务工具"
                ) from None
            finally:
                await manager.close()

    @app.put("/api/admin/users/{user_id}")
    async def save_user(user_id: str, body: Change, token: Annotated[str, Depends(admin)]) -> dict:
        _, state = store.read()
        old = next((u for u in state["users"] if u["id"] == user_id), None)
        if set(body.value) - {
            "name",
            "tenant_id",
            "roles",
            "servers",
            "enabled",
            "rules",
            "rate_limit",
            "secret_refs",
        }:
            raise HTTPException(400, "用户字段不受支持")
        issued = secrets.token_urlsafe(32) if old is None else None
        user = {
            "id": user_id,
            "name": user_id,
            "tenant_id": "default",
            "roles": [],
            "servers": [],
            "enabled": True,
            **(old or {}),
            **body.value,
            "token_hash": old["token_hash"] if old else token_hash(issued or ""),
        }
        state["users"] = [u for u in state["users"] if u["id"] != user_id] + [user]
        result = await apply(body, token, state)
        if issued:
            result["issued_token"] = issued
        return result

    @app.post("/api/admin/users/{user_id}/rotate")
    async def rotate_user(
        user_id: str, body: Change, token: Annotated[str, Depends(admin)]
    ) -> dict:
        _, state = store.read()
        user = next((u for u in state["users"] if u["id"] == user_id), None)
        if user is None:
            raise HTTPException(404, "用户不存在")
        issued = secrets.token_urlsafe(32)
        user["token_hash"] = token_hash(issued)
        result = await apply(body, token, state)
        result["issued_token"] = issued
        return result

    @app.delete("/api/admin/users/{user_id}")
    async def delete_user(
        user_id: str, body: Change, token: Annotated[str, Depends(admin)]
    ) -> dict:
        _, state = store.read()
        state["users"] = [u for u in state["users"] if u["id"] != user_id]
        return await apply(body, token, state)

    @app.put("/api/admin/model")
    async def save_model(body: Change, token: Annotated[str, Depends(admin)]) -> dict:
        _, state = store.read()
        if set(body.value) - {
            "base_url",
            "model",
            "api_key_env",
            "reasoning_effort",
            "protocol",
            "fallbacks",
        }:
            raise HTTPException(400, "模型配置字段不受支持")
        state["model"] = body.value
        return await apply(body, token, state)

    @app.put("/api/admin/secrets/{name}")
    async def save_secret(name: str, body: Change, token: Annotated[str, Depends(admin)]) -> dict:
        _, state = store.read()
        value = body.value.get("secret")
        if value is None:
            state["secrets"].pop(name, None)
        elif not isinstance(value, str) or not value or len(value) > 16384:
            raise HTTPException(400, "凭证值为空或过长")
        else:
            state["secrets"][name] = value
        return await apply(body, token, state)

    @app.post("/api/admin/model/test")
    async def test_model(token: Annotated[str, Depends(admin)]) -> dict:
        model = store.read()[1]["model"]
        key = os.environ.get(model.get("api_key_env", ""), "")
        if not model or not key:
            raise HTTPException(400, "请配置模型及其凭证")
        config = ProviderConfig(
            model["base_url"],
            model["model"],
            key,
            reasoning_effort=model.get("reasoning_effort", "low"),
            max_output_tokens=128,
        )
        provider = (
            ResponsesProvider(config)
            if model.get("protocol", "responses") == "responses"
            else CompatibleProvider(config, model["protocol"])
        )
        try:
            result = await provider.complete(
                "只回复 OK。", [{"role": "user", "content": "连接测试"}], []
            )
            return {
                "status": result.get("status"),
                "model": result.get("model"),
                "usage": result.get("usage"),
            }
        except ProviderError as exc:
            raise HTTPException(502, f"模型接口测试失败：{exc.code}") from None
        finally:
            await provider.close()

    @app.get("/api/admin/events")
    async def events(token: Annotated[str, Depends(admin)]) -> dict:
        return {"events": store.events()}

    @app.get("/api/admin/history")
    async def history(token: Annotated[str, Depends(admin)]) -> dict:
        return {"history": store.history()}

    @app.get("/api/admin/templates")
    async def templates(token: Annotated[str, Depends(admin)]) -> dict:
        return {"templates": TEMPLATES}

    @app.post("/api/admin/templates/{template}/install")
    async def install_mcp(
        template: str, body: Change, token: Annotated[str, Depends(admin)]
    ) -> dict:
        if store.read()[0] != body.revision:
            raise HTTPException(409, "配置版本已变化")
        try:
            definition = await install_template(
                store.root, template, body.value["server_id"], body.value.get("repository")
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from None
        state = store.read()[1]
        state["servers"] = [s for s in state["servers"] if s["id"] != definition["id"]] + [
            definition
        ]
        for user in state["users"]:
            if "admin" in user["roles"] and definition["id"] not in user["servers"]:
                user["servers"].append(definition["id"])
        return await apply(body, token, state)

    @app.put("/api/admin/oauth/{provider}")
    async def save_oauth(
        provider: str, body: Change, token: Annotated[str, Depends(admin)]
    ) -> dict:
        state = store.read()[1]
        state.setdefault("oauth", {})[provider] = body.value
        return await apply(body, token, state)

    def authenticated_user(authorization: str | None) -> dict:
        user = store.authenticate((authorization or "").removeprefix("Bearer "))
        if user is None:
            raise HTTPException(401, "身份无效")
        return user

    @app.post("/api/oauth/{provider}/start")
    async def oauth_start(
        provider: str, authorization: Annotated[str | None, Header()] = None
    ) -> dict:
        user = authenticated_user(authorization)
        config = store.read()[1].get("oauth", {}).get(provider)
        if config is None:
            raise HTTPException(404, "OAuth提供方不存在")
        return {"url": runtime.oauth.begin(user["tenant_id"] + "/" + user["id"], provider, config)}

    @app.get("/api/oauth/callback")
    async def oauth_callback(state: str, code: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                await runtime.oauth.complete(state, code, store.read()[1].get("oauth", {}), client)
            return {"status": "authorized", "message": "授权完成，可关闭此页面并刷新工具连接"}
        except (ValueError, KeyError, httpx.HTTPError):
            raise HTTPException(400, "OAuth授权失败") from None

    @app.post("/api/oauth/{provider}/revoke")
    async def oauth_revoke(
        provider: str, authorization: Annotated[str | None, Header()] = None
    ) -> dict:
        user = authenticated_user(authorization)
        config = store.read()[1].get("oauth", {}).get(provider)
        if config is None:
            raise HTTPException(404)
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            await runtime.oauth.revoke(
                user["tenant_id"] + "/" + user["id"], provider, config, client
            )
        return {"status": "revoked"}

    @app.post("/api/admin/history/{revision}/restore")
    async def rollback(revision: int, body: Change, token: Annotated[str, Depends(admin)]) -> dict:
        try:
            historical = store.historical(revision)
        except ValueError:
            raise HTTPException(404, "历史版本不存在") from None
        historical["users"] = store.read()[1]["users"]
        for user in historical["users"]:
            user["servers"] = [
                key for key in user["servers"] if key in {s["id"] for s in historical["servers"]}
            ]
        return await apply(body, token, historical)

    @app.put("/api/admin/roles/{role}")
    async def role_rule(role: str, body: Change, token: Annotated[str, Depends(admin)]) -> dict:
        state = store.read()[1]
        state.setdefault("roles", {})[role] = body.value
        return await apply(body, token, state)

    @app.get("/api/admin/approvals")
    async def approvals(token: Annotated[str, Depends(admin)]) -> dict:
        return {"approvals": runtime.approvals.list()}

    @app.get("/api/admin/approvals/{identity}")
    async def approval_detail(identity: str, token: Annotated[str, Depends(admin)]) -> dict:
        try:
            return {"arguments": runtime.approvals.details(identity)}
        except ValueError:
            raise HTTPException(404, "审批不存在") from None

    @app.post("/api/admin/approvals/{identity}/decide")
    async def decide(identity: str, body: Change, token: Annotated[str, Depends(admin)]) -> dict:
        actor = store.authenticate(token)
        if actor is None:
            raise HTTPException(401)
        if type(body.value.get("approve")) is not bool:
            raise HTTPException(400, "approve必须为布尔")
        try:
            runtime.approvals.decide(identity, actor["id"], body.value["approve"])
        except ValueError:
            raise HTTPException(409, "审批已处理或已过期") from None
        store.event(
            {
                "action": "approval_decision",
                "approval_id": identity,
                "principal_id": actor["id"],
                "status": "approved" if body.value["approve"] else "rejected",
            }
        )
        return {"status": "approved" if body.value["approve"] else "rejected"}

    @app.post("/api/admin/agent")
    async def agent_task(body: AgentTask, token: Annotated[str, Depends(admin)]) -> dict:
        model = store.read()[1]["model"]
        key = os.environ.get(model.get("api_key_env", ""), "")
        if not model or not key:
            raise HTTPException(400, "请先保存模型配置和凭证")
        providers = []
        for choice in [model, *model.get("fallbacks", [])]:
            config = ProviderConfig(
                choice["base_url"],
                choice["model"],
                os.environ.get(choice["api_key_env"], ""),
                reasoning_effort=choice.get("reasoning_effort", "low"),
            )
            providers.append(
                ResponsesProvider(config)
                if choice.get("protocol", "responses") == "responses"
                else CompatibleProvider(config, choice["protocol"])
            )
        provider = RoutedProvider(providers)
        try:
            async with (
                asyncio.timeout(180),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(runtime),
                    base_url="http://mvs-local",
                    headers={"Authorization": "Bearer " + token},
                ) as gateway,
            ):
                return await run_agent(body.task, provider, gateway)
        except (ProviderError, AgentError, TimeoutError) as exc:
            raise HTTPException(502, f"模型执行中断：{type(exc).__name__}；未自动重试") from None
        finally:
            await provider.close()

    @app.get("/api/admin/result")
    async def result(ref: str, token: Annotated[str, Depends(admin)]) -> dict:
        user = store.authenticate(token)
        assert user is not None
        async with runtime.gate:
            service = next(
                service
                for principal, service in runtime.app.state.services.items()
                if principal.principal_id == user["id"]
            )
            try:
                data = asdict(await service.results.get(ref, (user["tenant_id"], user["id"])))
                if len(json.dumps(data).encode()) > 65536:
                    return {
                        "result_ref": ref,
                        "truncated": True,
                        "message": "结果较大，请通过cat分页读取",
                    }
                return data
            except ShellError:
                raise HTTPException(404, "结果不存在、过期或不属于当前主体") from None

    assets = Path(__file__).resolve().parents[1] / "web"
    if (assets / "assets").exists():
        app.mount("/assets", StaticFiles(directory=assets / "assets"), name="assets")

    @app.get("/")
    async def index() -> Response:
        if not (assets / "index.html").exists():
            return JSONResponse(
                {"detail": "缺少控制台资源；开发者请运行 web 下的 npm run build"}, status_code=503
            )
        return FileResponse(assets / "index.html")

    app.mount("/", runtime)
    return app
