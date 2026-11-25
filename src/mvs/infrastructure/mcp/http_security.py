import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig


async def check_url(url: str, config: ServerConfig) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname
    if (
        host not in config.http_allowed_hosts
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.scheme not in {"http", "https"}
    ):
        raise ShellError("POLICY_DENIED", "HTTP endpoint is not allowlisted")
    if parsed.scheme != "https" and not (
        config.http_allow_private and host in {"127.0.0.1", "::1"}
    ):
        raise ShellError("POLICY_DENIED", "HTTPS required except explicitly allowed loopback tests")
    addresses = await asyncio.get_running_loop().getaddrinfo(
        host, parsed.port or 443, type=socket.SOCK_STREAM
    )
    if not addresses or (
        not config.http_allow_private
        and any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses)
    ):
        raise ShellError("POLICY_DENIED", "Private, loopback or metadata endpoint is not allowed")
