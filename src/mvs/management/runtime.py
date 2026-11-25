"""管理配置代际切换；切换等待已有请求结束，失败时保留旧状态。"""

import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import HTTPException
from starlette.types import Receive, Scope, Send

from mvs.api.app import create_app
from mvs.config import parse_config
from mvs.infrastructure.storage.rate_limit import RateLimiter
from mvs.management.gate import RuntimeGate
from mvs.management.store import StateStore, validate_state
from mvs.security.approvals import ApprovalStore
from mvs.security.oauth import OAuthStore
from mvs.security.policy import Principal


class ManagedRuntime:
    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.gate = RuntimeGate()
        self.app: Any = None
        self.context: Any = None
        self.generation = 0
        self.current_state: dict | None = None
        self.approvals = ApprovalStore(store.root)
        self.oauth = OAuthStore(store.root)
        self.limiter = RateLimiter(store.root / "limits.sqlite3", os.environ.get("MVS_REDIS_URL"))

    async def start(self) -> None:
        revision, state = self.store.read()
        self.app, self.context = await self.build(state)
        self.generation = revision
        self.current_state = state

    async def build(self, state: dict) -> tuple[Any, Any]:
        configs = parse_config({"servers": state["servers"]})
        tokens, grants, rules, retained, credentials, resolvers = {}, {}, {}, {}, {}, {}
        old_state = self.current_state
        for user in state["users"]:
            if not user["enabled"]:
                continue
            principal = Principal(user["id"], user["tenant_id"], frozenset(user["roles"]))
            tokens[user["token_hash"]] = principal
            grants[user["tenant_id"], user["id"]] = set(user["servers"])
            credentials[user["tenant_id"], user["id"]] = {
                ref: state["secrets"][secret] for ref, secret in user.get("secret_refs", {}).items()
            }

            def resolver_for(identity: str) -> Callable[[str], Awaitable[str]]:
                async def resolve(provider: str) -> str:
                    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                        return await self.oauth.access(
                            identity, provider, state.get("oauth", {})[provider], client
                        )

                return resolve

            resolvers[user["tenant_id"], user["id"]] = resolver_for(
                user["tenant_id"] + "/" + user["id"]
            )
            restrictions = ([user["rules"]] if "rules" in user else []) + [
                state.get("roles", {}).get(role, {}) for role in user["roles"] if role != "admin"
            ]
            if restrictions:
                rules[user["tenant_id"], user["id"]] = restrictions
            if old_state and old_state["secrets"] == state["secrets"]:
                previous = self.app.state.services.get(principal)
                previous_user = next((u for u in old_state["users"] if u["id"] == user["id"]), None)
                expected = {key: value for key, value in configs.items() if key in user["servers"]}
                if (
                    previous
                    and previous.manager.configs == expected
                    and previous_user
                    and previous_user.get("rules") == user.get("rules")
                    and previous_user.get("secret_refs") == user.get("secret_refs")
                    and old_state.get("oauth") == state.get("oauth")
                    and old_state.get("roles") == state.get("roles")
                ):
                    retained[principal] = previous
        for name, value in state["secrets"].items():
            os.environ[name] = value
        app = create_app(
            configs,
            tokens,
            grants,
            self.store.root / "results",
            hashed_tokens=True,
            record_event=self.store.event,
            rules=rules,
            retained_services=retained,
            approvals=self.approvals,
            credentials=credentials,
            oauth_resolvers=resolvers,
            metrics_override=self.app.state.telemetry if self.app else None,
        )
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        if self.app:
            for principal, service in app.state.services.items():
                old = self.app.state.services.get(principal)
                if old and service is not old:
                    service.sessions = old.sessions
        return app, context

    async def apply(self, expected: int, state: dict, token: str) -> int:
        validate_state(state)
        async with self.gate:
            actor = self.store.authenticate(token)
            if actor is None or "admin" not in actor["roles"]:
                raise HTTPException(403, "管理员授权已撤销")
            revision, old_state = self.store.read()
            if revision != expected:
                raise HTTPException(409, "配置版本冲突，请刷新页面")
            env_before = {
                key: os.environ.get(key)
                for key in old_state["secrets"].keys() | state["secrets"].keys()
            }
            app, context = None, None
            try:
                for key in old_state["secrets"].keys() - state["secrets"].keys():
                    os.environ.pop(key, None)
                app, context = await self.build(state)
                new_revision = self.store.save(expected, state)
            except BaseException:
                if context:
                    await context.__aexit__(None, None, None)
                for key, value in env_before.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                raise
            old_context = self.context
            if self.app:
                reused = set(app.state.services.values()) & set(self.app.state.services.values())
                self.app.state.owned_services.difference_update(reused)
                app.state.owned_services.update(reused)
            self.app, self.context, self.generation = app, context, new_revision
            self.current_state = state
            if old_context:
                await old_context.__aexit__(None, None, None)
            self.store.event(
                {
                    "action": "configuration_applied",
                    "principal_id": actor["id"],
                    "revision": new_revision,
                    "status": "success",
                }
            )
            return new_revision

    async def close(self) -> None:
        if self.context:
            await self.context.__aexit__(None, None, None)
        self.approvals.close()
        self.oauth.close()
        self.limiter.close()

    async def synchronize(self) -> None:
        revision, _ = self.store.read()
        if revision == self.generation:
            return
        async with self.gate:
            # 等待在途请求时其他节点仍可能发布新版本，不能应用排队前的旧快照。
            revision, state = self.store.read()
            if revision == self.generation:
                return
            app, context = await self.build(state)
            reused = set(app.state.services.values()) & set(self.app.state.services.values())
            self.app.state.owned_services.difference_update(reused)
            app.state.owned_services.update(reused)
            old = self.context
            self.app, self.context, self.generation = app, context, revision
            self.current_state = state
            await old.__aexit__(None, None, None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if os.environ.get("MVS_CONTROL_POSTGRES_DSN"):
            await self.synchronize()
        async with self.gate.read():
            if scope["type"] == "http" and scope.get("path", "").endswith("/shell/execute"):
                from starlette.responses import JSONResponse

                headers = dict(scope.get("headers", []))
                token = headers.get(b"authorization", b"").decode().removeprefix("Bearer ")
                user = self.store.authenticate(token)
                if user and not self.limiter.allow(
                    user["tenant_id"], user["id"], user.get("rate_limit", 60)
                ):
                    await JSONResponse({"detail": "请求速率超限"}, status_code=429)(
                        scope, receive, send
                    )
                    return
            await self.app(scope, receive, send)
