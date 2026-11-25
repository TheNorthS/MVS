import base64
import posixpath
import re
from dataclasses import dataclass
from enum import StrEnum

from mvs.domain.errors import ShellError
from mvs.domain.models import ToolDescriptor


class NodeType(StrEnum):
    DIRECTORY = "directory"
    TOOL = "tool"
    RESOURCE = "resource"
    RESOURCE_TEMPLATE = "resource_template"
    PROMPT = "prompt"
    RESULT = "result"


@dataclass(frozen=True)
class VFSNode:
    path: str
    name: str
    node_type: NodeType
    server_id: str | None = None
    target_name: str | None = None
    uri: str | None = None
    registry_revision: str | None = None


def encode_name(name: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.-]+", name) and name not in {".", ".."}:
        return name
    return "~" + base64.urlsafe_b64encode(name.encode()).decode().rstrip("=")


class VirtualFileSystem:
    def __init__(self) -> None:
        self.nodes: dict[str, VFSNode] = {}
        self.rebuild({})

    def rebuild(self, registry_snapshot: dict[tuple[str, str], ToolDescriptor]) -> None:
        nodes = {
            path: VFSNode(path, path.rsplit("/", 1)[-1], NodeType.DIRECTORY)
            for path in ("/", "/mcp", "/os")
        }
        for (server, name), tool in registry_snapshot.items():
            namespace = "os" if tool.backend == "native" else "mcp"
            root = f"/{namespace}/{server}"
            for path in (root, root + "/tools"):
                nodes[path] = VFSNode(path, path.rsplit("/", 1)[-1], NodeType.DIRECTORY, server)
            path = f"{root}/tools/{encode_name(name)}"
            nodes[path] = VFSNode(
                path,
                encode_name(name),
                NodeType.TOOL,
                server,
                name,
                registry_revision=tool.revision,
            )
        self.nodes = nodes

    def normalize(self, path: str, cwd: str) -> str:
        if (
            not path
            or len(path.encode()) > 4096
            or "\\" in path
            or "%" in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
        ):
            raise ShellError("INVALID_PATH", "Invalid virtual path")
        return "/" + posixpath.normpath(posixpath.join(cwd, path)).lstrip("/")

    def resolve(self, path: str, cwd: str, visible_servers: set[str]) -> VFSNode:
        node = self.nodes.get(self.normalize(path, cwd))
        if node is None or (node.server_id and node.server_id not in visible_servers):
            raise ShellError("NOT_FOUND", "Virtual node not found")
        return node

    def list_dir(self, path: str, cwd: str, visible_servers: set[str]) -> list[VFSNode]:
        node = self.resolve(path, cwd, visible_servers)
        if node.node_type != NodeType.DIRECTORY:
            raise ShellError("INVALID_PATH", "Expected a virtual directory")
        return sorted(
            (
                item
                for key, item in self.nodes.items()
                if key != node.path
                and posixpath.dirname(key) == node.path
                and (not item.server_id or item.server_id in visible_servers)
            ),
            key=lambda item: item.name,
        )
