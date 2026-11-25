import pytest

from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig
from mvs.infrastructure.mcp.http_security import check_url


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest",
        "file:///etc/passwd",
        "https://user:pass@127.0.0.1/mcp",
        "https://127.0.0.1/mcp",
    ],
)
async def test_http_denials(url):
    config = ServerConfig(
        "s",
        transport="streamable_http",
        url=url,
        http_allowed_hosts=("127.0.0.1", "169.254.169.254"),
    )
    with pytest.raises(ShellError):
        await check_url(url, config)
