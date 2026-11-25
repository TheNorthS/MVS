import asyncio

import pytest

from mvs.core.registry import Registry
from mvs.core.vfs import VirtualFileSystem, encode_name
from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig
from mvs.infrastructure.storage.session_store import SessionStore


def item(name="add"):
    return dict(
        name=name,
        title=None,
        description="",
        input_schema={"type": "object"},
        output_schema=None,
        annotations={},
    )


class Transport:
    def __init__(self):
        self.items = [item()]
        self.active = 0
        self.peak = 0

    async def list_tools(self, server_id, **kwargs):
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        if server_id == "broken":
            raise OSError("private details")
        return self.items


async def test_atomic_refresh_isolation_and_encoding():
    transport = Transport()
    registry = Registry(
        {s: ServerConfig(s, command="python") for s in ["demo", "broken"]}, transport
    )
    await registry.discover()
    assert registry.status == {"demo": "online", "broken": "offline"}
    old = registry.snapshot()
    transport.items = [item(name) for name in ["search", "a/b", "~YS9i", ".."]]
    await asyncio.gather(registry.refresh("demo"), registry.refresh("demo"))
    assert transport.peak <= 2  # different servers can discover concurrently
    assert list(old) == [("demo", "add")]
    vfs = VirtualFileSystem()
    vfs.rebuild(registry.snapshot())
    assert len({encode_name(x["name"]) for x in transport.items}) == 4
    for tool in transport.items:
        node = vfs.resolve("./" + encode_name(tool["name"]), "/mcp/demo/tools", {"demo"})
        assert node.target_name == tool["name"]
    assert vfs.list_dir("/mcp", "/", set()) == []
    with pytest.raises(ShellError):
        vfs.resolve("/mcp/demo", "/", set())
    assert vfs.normalize("../../../../", "/") == "/"
    for path in ["/etc/passwd", "/workspace"]:
        with pytest.raises(ShellError):
            vfs.resolve(path, "/", {"demo"})


@pytest.mark.parametrize("path", ["C:\\Windows", "/mcp/%2e%2e", "/a\x00", "/a\x7f", "a" * 4097])
def test_invalid_paths(path):
    with pytest.raises(ShellError) as exc:
        VirtualFileSystem().normalize(path, "/")
    assert exc.value.code == "INVALID_PATH"


def test_sessions():
    store = SessionStore()
    a, b = store.create("a", "tenant"), store.create("b", "tenant")
    a.cwd = "/mcp"
    assert b.cwd == "/"
    with pytest.raises(ShellError):
        store.get(a.session_id, "b", "tenant")
    with pytest.raises(ShellError):
        store.get(a.session_id, "a", "other-tenant")
    a.expires_at = 0
    with pytest.raises(ShellError):
        store.get(a.session_id, "a", "tenant")
