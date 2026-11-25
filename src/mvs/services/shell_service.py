import asyncio
import json
import logging
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from mvs.core.catalog import Catalog
from mvs.core.registry import Registry
from mvs.core.result_normalizer import preview
from mvs.core.schema_adapter import SchemaAdapter
from mvs.core.vfs import NodeType, VFSNode, VirtualFileSystem
from mvs.domain.errors import ShellError
from mvs.domain.models import (
    ResultEnvelope,
    ServerConfig,
    SessionContext,
    ShellResponse,
    ToolInvocation,
)
from mvs.domain.ports import ResultStorage
from mvs.domain.telemetry import Telemetry
from mvs.infrastructure.mcp.client_manager import ClientManager
from mvs.infrastructure.mcp.executor import MCPExecutor
from mvs.infrastructure.storage.result_store import ResultStore
from mvs.infrastructure.storage.session_store import SessionStore
from mvs.parser.ast import CommandAST
from mvs.parser.parser import CommandParser
from mvs.pipeline.planner import PipelineParser
from mvs.pipeline.transforms import transform
from mvs.pipeline.types import pipe_value
from mvs.security.approvals import approval_context
from mvs.security.audit import audit
from mvs.security.policy import PolicyEngine, Principal


class ShellService:
    def __init__(
        self,
        configs: dict[str, ServerConfig],
        policy: PolicyEngine | None = None,
        *,
        pipelines: bool = True,
        storage_root: Path | None = None,
        result_store: ResultStorage | None = None,
        telemetry: Telemetry | None = None,
        approvals: Any = None,
        credentials: dict | None = None,
        oauth_resolver: Any = None,
    ) -> None:
        self.telemetry = telemetry or Telemetry()
        self.approvals = approvals
        self.manager = ClientManager(configs, credentials, oauth_resolver)
        self.registry = Registry(configs, self.manager, self.telemetry)
        self.catalog = Catalog(configs)
        if os.environ.get("MVS_REDIS_URL"):
            from mvs.infrastructure.storage.redis_sessions import RedisSessionStore

            self.sessions: Any = RedisSessionStore(os.environ["MVS_REDIS_URL"])
        else:
            self.sessions = SessionStore()
        # Local CLI's explicit administrator grant; API supplies its own policy.
        self.policy = policy or PolicyEngine(configs, {("local", "local"): set(configs)})
        self.parser = PipelineParser() if pipelines else CommandParser()
        if result_store is None and os.environ.get("MVS_POSTGRES_DSN"):
            from mvs.infrastructure.storage.postgres_results import PostgresResultStore

            result_store = PostgresResultStore(
                os.environ["MVS_POSTGRES_DSN"],
                bucket=os.environ.get("MVS_S3_BUCKET"),
                endpoint_url=os.environ.get("MVS_S3_ENDPOINT"),
            )
        self.results: ResultStorage = result_store or ResultStore(
            storage_root or Path(".mvs"), telemetry=self.telemetry
        )
        self.adapter = SchemaAdapter()
        self.executor = MCPExecutor(self.manager, self.registry, self.telemetry)
        self.last_refresh: dict[str, float] = {}

    async def start(self) -> None:
        await self.registry.discover()
        for server in self.manager.connections:
            await self.refresh_catalog(server)
        self.last_refresh = dict.fromkeys(self.manager.configs, time.monotonic())

    async def refresh_due(self) -> None:
        for server, config in self.manager.configs.items():
            if (
                not config.enabled
                or time.monotonic() - self.last_refresh.get(server, 0) < config.refresh_ttl_seconds
            ):
                continue
            self.last_refresh[server] = time.monotonic()
            try:
                if self.registry.status[server] != "online":
                    await self.manager.disconnect(server)
                await self.registry.refresh(server)
                await self.refresh_catalog(server)
            except ShellError as exc:
                logging.getLogger("mvs").warning(
                    "Refresh failed server=%s code=%s", server, exc.code
                )
        await self.results.delete_expired()

    async def refresh_catalog(self, server: str) -> None:
        try:
            connection = await self.manager.connect(server)
            self.catalog.publish(server, await connection.list_catalog())
        except Exception as exc:
            self.catalog.publish(server, {})
            logging.getLogger("mvs").warning(
                "Catalog unavailable server=%s class=%s", server, type(exc).__name__
            )

    async def close(self) -> None:
        await self.manager.close()
        self.results.close()

    async def execute(self, command: str, context: SessionContext) -> ShellResponse:
        with self.telemetry.span("mvs.shell.execute", session_id=context.session_id):
            return await self._execute(command, context)

    async def _execute(self, command: str, context: SessionContext) -> ShellResponse:
        started = time.monotonic()
        response = ShellResponse(uuid4().hex, context.session_id)
        self.telemetry.annotate(**{"mvs.request_id": response.request_id})
        event: dict = dict(
            request_id=response.request_id,
            trace_id=self.telemetry.trace_id() or response.request_id,
            session_id=context.session_id,
            principal_id=context.principal_id,
            tenant_id=context.tenant_id,
            input_size_bytes=len(command.encode()),
        )
        try:
            session = self.sessions.get(context.session_id, context.principal_id, context.tenant_id)
            async with asyncio.timeout(30), self.sessions.locks[session.session_id]:
                session = self.sessions.get(
                    context.session_id, context.principal_id, context.tenant_id
                )
                ast = self.parser.parse(command)
                event["command"] = ast.verb
                principal = Principal(session.principal_id, session.tenant_id)
                try:
                    await self.dispatch(ast, session, principal, response, event)
                finally:
                    self.sessions.persist(session)
                response.stdout, clipped = preview(response.stdout)
                response.truncated |= clipped
                if len(json.dumps(response.data).encode()) > 8192:
                    response.data = {"preview": response.stdout, "untrusted": True}
                    response.truncated = True
        except TimeoutError:
            response.status, response.exit_code = "error", 1
            response.error = {"code": "TIMEOUT_UNCERTAIN", "message": "Request deadline exceeded"}
            response.stderr = "TIMEOUT_UNCERTAIN: Request deadline exceeded"
        except ShellError as exc:
            response.status = "approval_required" if exc.code == "APPROVAL_REQUIRED" else "error"
            response.exit_code = 1
            response.error = exc.as_dict()
            response.stderr = f"{exc.code}: {exc.message}"
        except asyncio.CancelledError:
            event["error_code"] = "CANCELLED_UNCERTAIN"
            self.telemetry.shell_finished(
                event.get("command", "unknown"), "cancelled", time.monotonic() - started
            )
            audit(event)
            raise
        except Exception as exc:
            # Exception class is useful to operators; raw transport/argument text is not safe.
            logging.getLogger("mvs").error("Internal failure class=%s", type(exc).__name__)
            response.status, response.exit_code = "error", 1
            response.error = {"code": "INTERNAL_ERROR", "message": "Internal execution failure"}
            response.stderr = "INTERNAL_ERROR: Internal execution failure"
        response.duration_ms = int((time.monotonic() - started) * 1000)
        event.update(
            duration_ms=response.duration_ms,
            success=response.status == "success",
            error_code=response.error["code"] if response.error else None,
            output_size_bytes=len(json.dumps(response.data).encode()),
        )
        audit(event)
        self.telemetry.annotate(**{"mvs.status": response.status})
        self.telemetry.shell_finished(
            event.get("command", "unknown"), response.status, time.monotonic() - started
        )
        return response

    async def dispatch(
        self,
        ast: CommandAST,
        session: SessionContext,
        principal: Principal,
        response: ShellResponse,
        event: dict,
    ) -> None:
        owner = (principal.tenant_id, principal.principal_id)
        if ast.kind == "pipeline":
            await self.dispatch(ast.stages[0], session, principal, response, event)
            if response.status != "success":
                return
            if response.result_ref:
                original = await self.results.get(response.result_ref, owner)
                data = original.structured_data
                if data is None:
                    data = "\n".join(original.text_blocks)
            else:
                data = response.data
            value = pipe_value(data, response.result_ref)
            for stage in ast.stages[1:]:
                if os.environ.get("MVS_ISOLATED_VALIDATION") == "1":
                    from mvs.infrastructure.native.isolated import isolated_operation

                    data = await isolated_operation(
                        {
                            "operation": "transform",
                            "data": value.value,
                            "verb": stage.verb,
                            "args": stage.args,
                        }
                    )
                    value = pipe_value(data, value.source_ref)
                else:
                    value = transform(value, stage.verb, stage.args)
            result = ResultEnvelope(
                response.request_id,
                "",
                "pipeline",
                True,
                value.value,
                metadata={"untrusted": True, "source_ref": response.result_ref},
            )
            response.result_ref = await self.results.put(result, owner)
            response.data = value.value
            response.stdout = (
                value.value
                if isinstance(value.value, str)
                else json.dumps(value.value, ensure_ascii=False)
            )
            return
        if ast.verb == "cat" and (ast.target or "").startswith("/results/"):
            result = await self.results.get(ast.target or "", owner)
            data = result.structured_data
            if ast.options:
                args = self.adapter.adapt(
                    ast.options,
                    {
                        "type": "object",
                        "properties": {
                            "offset": {"type": "integer", "minimum": 0},
                            "limit": {"type": "integer", "minimum": 0, "maximum": 1000},
                        },
                        "additionalProperties": False,
                    },
                )
                data = await self.results.slice(
                    ast.target or "", owner, args.get("offset", 0), args.get("limit", 100)
                )
                # Store the page as the pipeline source, avoiding a full-result reload.
                page = ResultEnvelope(response.request_id, "", "cat", True, data)
                response.result_ref = await self.results.put(page, owner)
            else:
                response.result_ref = ast.target
            response.data = data
            response.stdout = (
                "\n".join(result.text_blocks)
                if data is None
                else json.dumps(data, ensure_ascii=False)
            )
            if result.asset_refs:
                response.data = {
                    "structured_data": data,
                    "asset_refs": result.asset_refs,
                    "untrusted": True,
                }
            return
        if ast.verb == "refresh":
            server = ast.target or ""
            if ast.options:
                raise ShellError("INVALID_ARGUMENT", "refresh takes no options")
            if self.policy.authorize_discovery(principal, server).outcome != "allow":
                self.telemetry.policy_denied(server, "server_not_granted")
                raise ShellError("NOT_FOUND", "Server not found")
            await self.registry.refresh(server)
            await self.refresh_catalog(server)
            response.data, response.stdout = {"refreshed": server}, server
            return
        visible = self.policy.visible_servers(principal)
        snapshot = self.policy.visible_tools(principal, self.registry.snapshot())
        vfs = VirtualFileSystem()
        vfs.rebuild(snapshot)
        for server in visible:
            namespace = "os" if self.manager.configs[server].transport == "native" else "mcp"
            for path in (f"/{namespace}/{server}", f"/{namespace}/{server}/tools"):
                vfs.nodes.setdefault(
                    path, VFSNode(path, path.rsplit("/", 1)[-1], NodeType.DIRECTORY, server)
                )
        vfs.nodes["/results"] = VFSNode("/results", "results", NodeType.DIRECTORY)
        self.catalog.extend_vfs(vfs, visible)
        for path, catalog_node in list(vfs.nodes.items()):
            if catalog_node.node_type in {
                NodeType.RESOURCE,
                NodeType.RESOURCE_TEMPLATE,
                NodeType.PROMPT,
            }:
                kind = "prompts" if catalog_node.node_type == NodeType.PROMPT else "resources"
                name = catalog_node.target_name if kind == "prompts" else catalog_node.uri
                if not self.policy.permits(
                    principal, catalog_node.server_id or "", kind, name or ""
                ):
                    del vfs.nodes[path]
        if ast.target:
            # Observe only an explicit denied target; keep NOT_FOUND public semantics.
            requested = vfs.normalize(ast.target, session.cwd).split("/")
            if len(requested) >= 3 and requested[1] in {"mcp", "os"}:
                server = requested[2]
                if server not in visible:
                    self.telemetry.policy_denied(server, "server_not_granted")
                elif len(requested) == 5 and requested[3] == "tools":
                    from mvs.core.vfs import encode_name

                    denied = next(
                        (
                            tool
                            for (s, _), tool in self.registry.snapshot().items()
                            if s == server and encode_name(tool.name) == requested[4]
                        ),
                        None,
                    )
                    if (
                        denied
                        and self.policy.authorize_call(principal, denied, {}).outcome == "deny"
                    ):
                        self.telemetry.policy_denied(server, "tool_not_allowed")
        if ast.verb in {"cat", "read", "prompt"}:
            node = vfs.resolve(ast.target or "", session.cwd, visible)
            item = self.catalog.items.get(node.path)
            if item is None or (ast.verb == "prompt") != (node.node_type == NodeType.PROMPT):
                raise ShellError("INVALID_PATH", "Expected a resource or prompt node")
            config = self.manager.configs[item["server"]]
            allowlist = config.allowed_prompts if ast.verb == "prompt" else config.allowed_resources
            binding = item["name"] if ast.verb == "prompt" else item["uri"]
            if binding not in allowlist:
                self.telemetry.policy_denied(item["server"], "catalog_not_allowed")
                raise ShellError("POLICY_DENIED", "Catalog access was revoked")
            if session.calls >= session.max_calls:
                raise ShellError("LIMIT_EXCEEDED", "Session call quota exceeded")
            args = self.adapter.adapt(ast.options, self.catalog.parameters(item))
            if not self.policy.permits(
                principal,
                item["server"],
                "prompts" if ast.verb == "prompt" else "resources",
                binding,
                args,
            ):
                raise ShellError("POLICY_DENIED", "资源或提示词参数不符合用户授权")
            session.calls += 1
            connection = self.manager.connections.get(item["server"])
            if connection is None:
                raise ShellError("SERVER_OFFLINE", "Server is offline")
            try:
                raw = (
                    await connection.get_prompt(item["name"], args)
                    if ast.verb == "prompt"
                    else await connection.read_resource(self.catalog.expand(item, args))
                )
            except TimeoutError:
                raise ShellError("TIMEOUT_UNCERTAIN", "Catalog request timed out") from None
            invocation = ToolInvocation(item["server"], item["name"], args, "", response.request_id)
            result = self.executor.normalizer.normalize(raw, invocation, None, 0)
            assets = {ref: self.executor.normalizer.assets.pop(ref) for ref in result.asset_refs}
            self.executor.normalizer.asset_bytes -= sum(
                len(json.dumps(b).encode()) for b in assets.values()
            )
            response.result_ref = await self.results.put(result, owner, assets=assets)
            response.stdout = "\n".join(result.text_blocks)
            response.data = {
                "text": response.stdout,
                "asset_refs": result.asset_refs,
                "untrusted": True,
            }
            event.update(server_id=item["server"], tool_name=item["name"])
            return
        if ast.kind == "builtin":
            response.data, response.stdout = self.builtin(ast, session, visible, vfs, snapshot)
            response.stdout, response.truncated = preview(response.stdout)
            return
        node = vfs.resolve(ast.target or "", session.cwd, visible)
        if node.node_type != NodeType.TOOL or not node.server_id or not node.target_name:
            raise ShellError("INVALID_PATH", "Expected a tool node")
        tool = self.registry.get(node.server_id, node.target_name)
        if os.environ.get("MVS_ISOLATED_VALIDATION") == "1":
            from mvs.infrastructure.native.isolated import isolated_operation

            isolated_args = await isolated_operation(
                {
                    "operation": "adapt",
                    "options": [asdict(o) for o in ast.options],
                    "schema": tool.input_schema,
                }
            )
            assert isinstance(isolated_args, dict)
            args = isolated_args
        else:
            args = self.adapter.adapt(ast.options, tool.input_schema)
        event.update(
            server_id=tool.server_id,
            tool_name=tool.name,
            registry_revision=tool.revision,
            backend=tool.backend,
        )
        decision = self.policy.authorize_call(principal, tool, args)
        if decision.outcome != "allow":
            if decision.outcome == "approval_required" and self.approvals:
                if approval_context.get() is None:
                    approval_id = self.approvals.request(principal, tool, args)
                    raise ShellError(
                        "APPROVAL_REQUIRED", "调用已提交审批，有效期10分钟", approval_id=approval_id
                    )
            else:
                self.telemetry.policy_denied(tool.server_id, decision.outcome)
                raise ShellError(
                    "APPROVAL_REQUIRED"
                    if decision.outcome == "approval_required"
                    else "POLICY_DENIED",
                    decision.reason,
                )
        if session.calls >= session.max_calls:
            raise ShellError("LIMIT_EXCEEDED", "Session call quota exceeded")
        session.calls += 1
        invocation = ToolInvocation(
            tool.server_id, tool.name, args, tool.revision, response.request_id
        )

        def preflight() -> None:
            outcome = self.policy.authorize_call(principal, tool, args).outcome
            if outcome == "approval_required" and self.approvals and approval_context.get():
                self.approvals.consume(approval_context.get(), principal, tool, args)
                approval_context.set(None)
            elif outcome != "allow":
                self.telemetry.policy_denied(tool.server_id, "authorization_changed")
                raise ShellError("POLICY_DENIED", "Authorization changed while waiting")
            self.sessions.get(session.session_id, principal.principal_id, principal.tenant_id)

        result = await self.executor.invoke(invocation, preflight)
        if not result.success and tool.backend != "native":
            raise ShellError(result.error_code or "TOOL_EXECUTION_FAILED", "Tool returned an error")
        assets = {ref: self.executor.normalizer.assets.pop(ref) for ref in result.asset_refs}
        self.executor.normalizer.asset_bytes -= sum(
            len(json.dumps(b).encode()) for b in assets.values()
        )
        response.result_ref = await self.results.put(result, owner, assets=assets)
        response.data = result.structured_data
        if tool.backend == "native":
            response.stdout = result.structured_data["stdout"]
            response.stderr, stderr_clipped = preview(result.structured_data["stderr"])
            response.truncated |= stderr_clipped
            response.exit_code = result.structured_data["exit_code"]
            if not result.success:
                response.status = "error"
                response.error = {"code": result.error_code, "message": "原生命令以非零退出码结束"}
            return
        text = "\n".join(result.text_blocks)
        if isinstance(response.data, dict) and set(response.data) == {"result"}:
            value = response.data["result"]
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        response.stdout = text
        if result.asset_refs:
            response.data = {
                "structured_data": response.data,
                "asset_refs": result.asset_refs,
                "asset_types": result.metadata["asset_types"],
                "untrusted": True,
            }

    def builtin(
        self,
        ast: CommandAST,
        session: SessionContext,
        visible: set[str],
        vfs: VirtualFileSystem,
        snapshot: dict,
    ) -> tuple[object, str]:
        if ast.verb == "pwd":
            return session.cwd, session.cwd
        if ast.verb == "exit":
            return {"exit": True}, ""
        if ast.verb == "servers":
            data = [{"id": key, "status": self.registry.status[key]} for key in sorted(visible)]
            return data, "\n".join(item["id"] for item in data)
        if ast.verb == "tools":
            if ast.target and ast.target not in visible:
                raise ShellError("NOT_FOUND", "Server not found")
            paths = [
                node.path
                for node in vfs.nodes.values()
                if node.node_type == NodeType.TOOL
                and (not ast.target or node.server_id == ast.target)
            ]
            return sorted(paths), "\n".join(sorted(paths))
        if ast.verb == "ls":
            nodes = vfs.list_dir(ast.target or session.cwd, session.cwd, visible)
            names = [
                node.name + ("/" if node.node_type == NodeType.DIRECTORY else "") for node in nodes
            ]
            return names, "\n".join(names)
        if ast.verb == "cd":
            node = vfs.resolve(ast.target or "", session.cwd, visible)
            if node.node_type != NodeType.DIRECTORY:
                raise ShellError("INVALID_PATH", "cd requires a directory")
            session.cwd = node.path
            return session.cwd, session.cwd
        if ast.verb == "help":
            if ast.target is None:
                text = (
                    "pwd ls cd help servers tools run exit; tool options: --key value / --key=value"
                )
                return text, text
            node = vfs.resolve(ast.target, session.cwd, visible)
            if node.node_type != NodeType.TOOL:
                raise ShellError("INVALID_PATH", "help requires a tool")
            tool = snapshot[node.server_id, node.target_name]
            text = self.adapter.render_help(tool)
            return {
                "input_schema": tool.input_schema,
                "untrusted": True,
                "backend": tool.backend,
            }, text
        raise ShellError("UNKNOWN_COMMAND", "Unknown builtin")
