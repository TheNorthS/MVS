import asyncio
import json
import os
from contextlib import AsyncExitStack
from typing import Any

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client

from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig
from mvs.infrastructure.mcp.http_security import check_url
from mvs.infrastructure.mcp.pinned_http import PinnedTransport


class SDKConnection:
    """Enter and exit the SDK context in one owner task (AnyIO scope requirement)."""

    def __init__(
        self, config: ServerConfig, credentials: dict | None = None, oauth_resolver: Any = None
    ) -> None:
        self.credentials = credentials or {}
        self.oauth_resolver = oauth_resolver
        self.config = config
        self.client: Client | None = None
        self.ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.stop = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.semaphore = asyncio.Semaphore(config.max_concurrency)

    async def start(self) -> None:
        self.task = asyncio.create_task(self._own())
        try:
            await asyncio.wait_for(asyncio.shield(self.ready), self.config.connect_timeout_seconds)
        except TimeoutError:
            await self.close()
            raise ShellError("SERVER_OFFLINE", "Server connection timed out") from None

    async def _own(self) -> None:
        try:
            async with AsyncExitStack() as stack:
                if self.config.transport == "stdio":
                    env = {
                        key: self.credentials.get(ref) or os.environ[ref]
                        for key, ref in self.config.env_refs.items()
                    }
                    target: Any = StdioServerParameters(
                        command=self.config.command or "", args=list(self.config.args), env=env
                    )
                else:
                    url = self.config.url or ""
                    await check_url(url, self.config)

                    async def guard(request: httpx2.Request) -> None:
                        origin = httpx2.URL(url)
                        if (request.url.scheme, request.url.host, request.url.port) != (
                            origin.scheme,
                            origin.host,
                            origin.port,
                        ):
                            raise ShellError("POLICY_DENIED", "Cross-origin HTTP request denied")
                        await check_url(str(request.url), self.config)
                        if self.config.auth_ref and self.config.auth_ref.startswith("oauth:"):
                            if self.oauth_resolver is None:
                                raise ShellError("POLICY_DENIED", "OAuth未配置")
                            request.headers["Authorization"] = (
                                "Bearer " + await self.oauth_resolver(self.config.auth_ref[6:])
                            )

                    headers = {}
                    if self.config.auth_ref and not self.config.auth_ref.startswith("oauth:"):
                        headers["Authorization"] = "Bearer " + (
                            self.credentials.get(self.config.auth_ref)
                            or os.environ[self.config.auth_ref]
                        )
                    http = await stack.enter_async_context(
                        httpx2.AsyncClient(
                            transport=PinnedTransport(self.config),
                            headers=headers,
                            follow_redirects=False,
                            trust_env=False,
                            timeout=self.config.call_timeout_seconds,
                            event_hooks={"request": [guard]},
                        )
                    )
                    target = streamable_http_client(url, http_client=http)
                client = await stack.enter_async_context(Client(target))
                self.client = client
                self.ready.set_result(None)
                await self.stop.wait()
        except Exception:
            if not self.ready.done():
                self.ready.set_exception(ShellError("SERVER_OFFLINE", "Server connection failed"))
            else:
                # Lifecycle errors are observable as offline; never expose credentials/paths.
                self.stop.set()
        finally:
            self.client = None

    async def close(self) -> None:
        self.stop.set()
        if self.task:
            if not self.ready.done():
                self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    def connected(self) -> Client:
        if self.client is None:
            raise ShellError("SERVER_OFFLINE", "Server is offline")
        return self.client

    async def list_tools(self, *, refresh: bool = False) -> list[dict]:
        client = self.connected()
        result: list[dict] = []
        cursor = None
        seen = set()
        size = 0
        async with asyncio.timeout(self.config.discovery_timeout_seconds):
            for _ in range(100):
                page = await client.list_tools(
                    cursor=cursor, cache_mode="refresh" if refresh else "use"
                )
                for tool in page.tools:
                    item = {
                        "name": tool.name,
                        "title": tool.title,
                        "description": tool.description or "",
                        "input_schema": tool.input_schema,
                        "output_schema": tool.output_schema,
                        "annotations": (
                            tool.annotations.model_dump(mode="json") if tool.annotations else {}
                        ),
                    }
                    size += len(json.dumps(item).encode())
                    result.append(item)
                if len(result) > 10000 or size > 4 * 1024 * 1024:
                    raise ShellError("LIMIT_EXCEEDED", "Discovery metadata exceeds quota")
                cursor = page.next_cursor
                if cursor is None:
                    return result
                if cursor in seen:
                    raise ShellError("MCP_PROTOCOL_ERROR", "Repeated discovery cursor")
                seen.add(cursor)
        raise ShellError("LIMIT_EXCEEDED", "Too many discovery pages")

    async def call_tool(self, name: str, arguments: dict) -> dict[str, Any]:
        result = await self.connected().call_tool(name, arguments)
        return {
            "is_error": result.is_error,
            "structured_content": result.structured_content,
            "content": [block.model_dump(mode="json") for block in result.content],
        }

    async def list_catalog(self) -> dict[str, list[dict]]:
        client = self.connected()
        output = {}
        caps = client.server_capabilities
        for kind, capability, method in (
            ("resources", caps.resources, client.list_resources),
            ("resource_templates", caps.resources, client.list_resource_templates),
            ("prompts", caps.prompts, client.list_prompts),
        ):
            items: list[dict] = []
            cursor = None
            seen: set[str] = set()
            if capability is None:
                output[kind] = items
                continue
            async with asyncio.timeout(self.config.discovery_timeout_seconds):
                for _ in range(100):
                    page = await method(cursor=cursor, cache_mode="refresh")
                    items.extend(item.model_dump(mode="json") for item in getattr(page, kind))
                    if len(items) > 10000 or len(json.dumps(items).encode()) > 4 * 1024 * 1024:
                        raise ShellError("LIMIT_EXCEEDED", "Catalog quota exceeded")
                    cursor = page.next_cursor
                    if cursor is None:
                        break
                    if cursor in seen:
                        raise ShellError("MCP_PROTOCOL_ERROR", "Catalog cursor cycle")
                    seen.add(cursor)
                else:
                    raise ShellError("LIMIT_EXCEEDED", "Catalog page quota exceeded")
            output[kind] = items
        return output

    async def read_resource(self, uri: str) -> dict:
        async with self.semaphore, asyncio.timeout(self.config.call_timeout_seconds):
            result = await self.connected().read_resource(uri)
            return {
                "is_error": False,
                "structured_content": None,
                "content": [
                    {"type": "text", "text": item.text}
                    if hasattr(item, "text")
                    else {"type": "resource", **item.model_dump(mode="json")}
                    for item in result.contents
                ],
            }

    async def get_prompt(self, name: str, args: dict) -> dict:
        async with self.semaphore, asyncio.timeout(self.config.call_timeout_seconds):
            result = await self.connected().get_prompt(name, args)
            return {
                "is_error": False,
                "structured_content": None,
                "content": [item.content.model_dump(mode="json") for item in result.messages],
            }
