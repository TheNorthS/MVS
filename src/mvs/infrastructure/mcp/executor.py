import asyncio
import os
import time
from collections.abc import Callable

from mcp.shared.exceptions import MCPError

from mvs.core.registry import Registry
from mvs.core.result_normalizer import ResultNormalizer
from mvs.domain.errors import ShellError
from mvs.domain.models import ResultEnvelope, ToolInvocation
from mvs.domain.telemetry import Telemetry
from mvs.infrastructure.mcp.client_manager import ClientManager


class MCPExecutor:
    def __init__(
        self, manager: ClientManager, registry: Registry, telemetry: Telemetry | None = None
    ) -> None:
        self.telemetry = telemetry or Telemetry()
        self.manager = manager
        self.registry = registry
        self.normalizer = ResultNormalizer()
        self.semaphores = {
            key: asyncio.Semaphore(config.max_concurrency)
            for key, config in manager.configs.items()
        }

    async def invoke(
        self, invocation: ToolInvocation, preflight: Callable[[], None] | None = None
    ) -> ResultEnvelope:
        started = time.monotonic()
        state = {"dispatched": False}
        status = "error"
        try:
            with self.telemetry.span(
                "mvs.tool.invoke",
                server=invocation.server_id,
                tool=invocation.tool_name,
                request_id=invocation.request_id,
            ):
                result = await self._invoke(invocation, preflight, state)
            status = "success" if result.success else "error"
            return result
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except ShellError as exc:
            if exc.code == "TIMEOUT_UNCERTAIN":
                status = "timeout"
            raise
        finally:
            if state["dispatched"]:
                observe = (
                    self.telemetry.native_finished
                    if self.manager.configs[invocation.server_id].transport == "native"
                    else self.telemetry.tool_finished
                )
                observe(
                    invocation.server_id, invocation.tool_name, status, time.monotonic() - started
                )

    async def _invoke(
        self,
        invocation: ToolInvocation,
        preflight: Callable[[], None] | None,
        state: dict[str, bool],
    ) -> ResultEnvelope:
        start = time.monotonic()
        config = self.manager.configs[invocation.server_id]
        try:
            async with asyncio.timeout(config.call_timeout_seconds):
                async with self.semaphores[invocation.server_id]:
                    tool = self.registry.get(invocation.server_id, invocation.tool_name)
                    if tool.revision != invocation.registry_revision:
                        raise ShellError("TOOL_CHANGED", "Tool changed; refresh and retry planning")
                    if preflight:
                        preflight()
                    state["dispatched"] = True
                    raw = await self.manager.call_tool(
                        invocation.server_id, invocation.tool_name, invocation.arguments
                    )
        except TimeoutError:
            raise ShellError(
                "TIMEOUT_UNCERTAIN", "Timed out; server may have executed the call"
            ) from None
        except MCPError as exc:
            if exc.code == -32001:
                raise ShellError(
                    "TIMEOUT_UNCERTAIN", "SDK timed out; call may have executed"
                ) from None
            raise ShellError("MCP_PROTOCOL_ERROR", "MCP protocol request failed") from None
        except ShellError:
            raise
        except Exception:
            self.registry.status[invocation.server_id] = "offline"
            raise ShellError(
                "SERVER_OFFLINE", "Connection lost; execution may have occurred"
            ) from None
        output_schema = tool.output_schema
        if (
            output_schema
            and not raw.get("is_error")
            and os.environ.get("MVS_ISOLATED_VALIDATION") == "1"
        ):
            from mvs.infrastructure.native.isolated import isolated_operation

            try:
                await isolated_operation(
                    {
                        "operation": "validate",
                        "schema": output_schema,
                        "data": raw.get("structured_content"),
                    }
                )
            except ShellError:
                raise ShellError("INVALID_TOOL_OUTPUT", "工具结果未通过隔离Schema验证") from None
            output_schema = None
        return self.normalizer.normalize(
            raw, invocation, output_schema, int((time.monotonic() - start) * 1000)
        )
