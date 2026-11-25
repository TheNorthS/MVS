"""在实际TCP连接点解析、检查并绑定IP；TLS SNI和Host仍使用原主机名。"""

import asyncio
import ipaddress
import socket
import ssl
from typing import Any

import httpcore2
import httpx2
from httpcore2._backends.auto import AutoBackend

from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig


class PinnedBackend(AutoBackend):
    def __init__(self, config: ServerConfig) -> None:
        self.config = config

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore后端接口
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        if host not in self.config.http_allowed_hosts:
            raise ShellError("POLICY_DENIED", "连接主机未获授权")
        addresses = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout or 10,
        )
        ips = list(dict.fromkeys(str(row[4][0]) for row in addresses))
        if not ips or (
            not self.config.http_allow_private
            and any(not ipaddress.ip_address(ip).is_global for ip in ips)
        ):
            raise ShellError("POLICY_DENIED", "连接解析到了不允许的网络地址")
        # numeric IP 不再进行第二次域名解析，防止检查与连接之间DNS替换。
        return await super().connect_tcp(ips[0], port, timeout, local_address, socket_options)


class PinnedTransport(httpx2.AsyncHTTPTransport):
    def __init__(self, config: ServerConfig) -> None:
        super().__init__(trust_env=False, retries=0)
        self._pool = httpcore2.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PinnedBackend(config),
            retries=0,
        )
