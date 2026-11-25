"""Real SDK v2 in-process protocol fixture, isolated from model-provider credentials."""

import json
from typing import Any

from mcp.server.lowlevel import Server
from mcp.types import CallToolResult, TextContent, Tool

from mvs.benchmarks.workload import tool_result
from mvs.core.schema_adapter import SchemaAdapter
from mvs.domain.errors import ShellError


def make_server(definitions: list[dict], calls: list[dict]) -> Server:
    tools = {item["name"]: item for item in definitions}

    async def list_tools(context: Any, params: Any) -> Any:
        from mcp.types import ListToolsResult

        return ListToolsResult(tools=[Tool(**tool) for tool in definitions])

    async def call_tool(context: Any, params: Any) -> CallToolResult:
        name, args = params.name, params.arguments or {}
        calls.append({"name": name, "arguments": args})
        try:
            if name not in tools:
                raise ShellError("NOT_FOUND", "Tool not found")
            SchemaAdapter().validate(args, tools[name]["input_schema"])
            data = tool_result(name, args)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(data))],
                structured_content=data,
                is_error=False,
            )
        except ShellError as exc:
            return CallToolResult(content=[TextContent(type="text", text=exc.code)], is_error=True)

    return Server("mvs-benchmark", on_list_tools=list_tools, on_call_tool=call_tool)


class BenchmarkConnection:
    """Context-managed fixture with a ClientManager-compatible connection."""

    def __init__(self, definitions: list[dict], calls: list[dict], config: Any) -> None:
        from mcp import Client

        self.client = Client(make_server(definitions, calls))
        self.config = config

    async def __aenter__(self) -> Any:
        from mvs.infrastructure.mcp.sdk_v2_adapter import SDKConnection

        await self.client.__aenter__()
        self.connection = SDKConnection(self.config)
        self.connection.client = self.client
        return self.connection

    async def __aexit__(self, *exc: Any) -> None:
        await self.client.__aexit__(*exc)
