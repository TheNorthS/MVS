import asyncio
import hashlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field

from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig, SessionContext
from mvs.infrastructure.observability import PrometheusTelemetry
from mvs.security.approvals import approval_context
from mvs.security.policy import PolicyEngine, Principal
from mvs.services.shell_service import ShellService


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(max_length=128)
    command: str = Field(max_length=16384)
    approval_id: str | None = Field(default=None, max_length=64)


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def create_app(
    configs: dict[str, ServerConfig],
    tokens: dict[str, Principal],
    grants: dict[tuple[str, str], set[str]],
    storage_root: Path | None = None,
    *,
    hashed_tokens: bool = False,
    record_event: Callable[[dict], None] | None = None,
    rules: dict | None = None,
    retained_services: dict | None = None,
    approvals: Any = None,
    credentials: dict | None = None,
    oauth_resolvers: dict | None = None,
    metrics_override: PrometheusTelemetry | None = None,
) -> FastAPI:
    if not tokens or any(len(token) < 24 for token in tokens):
        raise ValueError("API requires administrator tokens of at least 24 characters")
    metrics = metrics_override or PrometheusTelemetry(set(configs))
    metrics.servers = frozenset(configs)
    services = {
        principal: ShellService(
            {
                key: value
                for key, value in configs.items()
                if key in grants.get((principal.tenant_id, principal.principal_id), set())
            },
            PolicyEngine(configs, grants, rules),
            storage_root=storage_root,
            telemetry=metrics,
            approvals=approvals,
            credentials=(credentials or {}).get((principal.tenant_id, principal.principal_id)),
            oauth_resolver=(oauth_resolvers or {}).get(
                (principal.tenant_id, principal.principal_id)
            ),
        )
        for principal in set(tokens.values())
    }
    tracer = trace.get_tracer("mvs.api")
    owned_services = set(services.values())
    for principal, retained in (retained_services or {}).items():
        if principal in services:
            services[principal].results.close()
            owned_services.discard(services[principal])
            services[principal] = retained

    async def refresh_loop(service: ShellService) -> None:
        while True:
            await asyncio.sleep(1)
            await service.refresh_due()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tasks = []
        try:
            for service in services.values():
                if service in owned_services:
                    await service.start()
                tasks.append(asyncio.create_task(refresh_loop(service)))
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for service in owned_services:
                await service.close()

    app = FastAPI(lifespan=lifespan)
    app.state.services = services
    app.state.telemetry = metrics
    app.state.owned_services = owned_services

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> Principal:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Authentication required")
        candidate = authorization[7:]
        if hashed_tokens:
            candidate = hashlib.sha256(candidate.encode()).hexdigest()
        for token, principal in tokens.items():
            if secrets.compare_digest(candidate, token):
                return principal
        raise HTTPException(401, "Authentication required")

    def session(service: ShellService, key: str, principal: Principal) -> SessionContext:
        try:
            return service.sessions.get(key, principal.principal_id, principal.tenant_id)
        except ShellError:
            raise HTTPException(404, "Session not found") from None

    @app.post("/api/v1/sessions")
    async def create_session(
        body: CreateSessionRequest, principal: Annotated[Principal, Depends(authenticate)]
    ) -> dict:
        return asdict(
            services[principal].sessions.create(principal.principal_id, principal.tenant_id)
        )

    @app.delete("/api/v1/sessions/{key}")
    async def delete_session(
        key: str, principal: Annotated[Principal, Depends(authenticate)]
    ) -> dict:
        service = services[principal]
        session(service, key, principal)
        service.sessions.delete(key, principal.principal_id, principal.tenant_id)
        return {"deleted": True}

    @app.post("/api/v1/shell/execute")
    async def execute(
        body: ExecuteRequest, principal: Annotated[Principal, Depends(authenticate)]
    ) -> dict:
        service = services[principal]
        context = session(service, body.session_id, principal)
        with tracer.start_as_current_span("mvs.api.execute") as span:
            approval_token = approval_context.set(body.approval_id)
            try:
                result = await service.execute(body.command, context)
            finally:
                approval_context.reset(approval_token)
            span.set_attribute("mvs.request_id", result.request_id)
            span.set_attribute("mvs.status", result.status)
            if record_event:
                record_event(
                    {
                        "request_id": result.request_id,
                        "principal_id": principal.principal_id,
                        "tenant_id": principal.tenant_id,
                        "status": result.status,
                        "duration_ms": result.duration_ms,
                        "error_code": (result.error or {}).get("code"),
                        "result_ref": result.result_ref,
                    }
                )
            return asdict(result)

    @app.get("/api/v1/servers")
    async def servers(principal: Annotated[Principal, Depends(authenticate)]) -> list:
        service = services[principal]
        return [
            {"id": key, "status": service.registry.status[key]}
            for key in sorted(service.policy.visible_servers(principal))
        ]

    @app.post("/api/v1/servers/{server}/refresh")
    async def refresh(server: str, principal: Annotated[Principal, Depends(authenticate)]) -> dict:
        service = services[principal]
        if "admin" not in principal.roles or server not in service.policy.visible_servers(
            principal
        ):
            metrics.policy_denied(
                server, "admin_required" if "admin" not in principal.roles else "server_not_granted"
            )
            raise HTTPException(403, "Administrator grant required")
        try:
            await service.registry.refresh(server)
            await service.refresh_catalog(server)
        except ShellError:
            raise HTTPException(503, "Server unavailable") from None
        return {"refreshed": server}

    @app.get("/api/v1/health/live")
    async def live() -> dict:
        return {"live": True}

    @app.get("/api/v1/health/ready")
    async def ready() -> dict:
        if any(
            any(
                state != "online"
                for key, state in service.registry.status.items()
                if configs[key].enabled
            )
            for service in services.values()
        ):
            raise HTTPException(503, "Dependencies unavailable")
        return {"ready": True}

    @app.get("/metrics")
    async def metric_export(principal: Annotated[Principal, Depends(authenticate)]) -> Response:
        if "admin" not in principal.roles:
            metrics.policy_denied("", "admin_required")
            raise HTTPException(403, "Administrator grant required")
        return Response(metrics.export(), media_type="text/plain; version=0.0.4; charset=utf-8")

    return app
