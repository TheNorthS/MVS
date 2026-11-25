import re
from urllib.parse import quote

from mvs.core.vfs import NodeType, VFSNode, VirtualFileSystem, encode_name
from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig


class Catalog:
    def __init__(self, configs: dict[str, ServerConfig]) -> None:
        self.configs = configs
        self.items: dict[str, dict] = {}

    def publish(self, server: str, catalog: dict) -> None:
        updated = {path: item for path, item in self.items.items() if item["server"] != server}
        config = self.configs[server]
        for kind, items in catalog.items():
            for item in items:
                name = item["name"]
                uri = item.get("uri") or item.get("uri_template")
                if kind == "prompts":
                    if name not in config.allowed_prompts:
                        continue
                elif uri not in config.allowed_resources:
                    continue
                key = uri if kind != "prompts" else name
                path = f"/mcp/{server}/{kind}/{encode_name(key)}"
                updated[path] = {**item, "server": server, "kind": kind, "uri": uri}
        self.items = updated

    def extend_vfs(self, vfs: VirtualFileSystem, visible: set[str]) -> None:
        for path, item in self.items.items():
            server = item["server"]
            if server not in visible:
                continue
            for directory in (f"/mcp/{server}", path.rsplit("/", 1)[0]):
                vfs.nodes[directory] = VFSNode(
                    directory, directory.rsplit("/", 1)[-1], NodeType.DIRECTORY, server
                )
            kind = {
                "resources": NodeType.RESOURCE,
                "resource_templates": NodeType.RESOURCE_TEMPLATE,
                "prompts": NodeType.PROMPT,
            }[item["kind"]]
            vfs.nodes[path] = VFSNode(
                path, path.rsplit("/", 1)[-1], kind, server, item["name"], item["uri"]
            )

    def parameters(self, item: dict) -> dict:
        if item["kind"] == "prompts":
            args = item.get("arguments") or []
            return {
                "type": "object",
                "properties": {arg["name"]: {"type": "string"} for arg in args},
                "required": [arg["name"] for arg in args if arg.get("required")],
                "additionalProperties": False,
            }
        names = re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", item["uri"])
        return {
            "type": "object",
            "properties": {name: {"type": "string"} for name in names},
            "required": names,
            "additionalProperties": False,
        }

    def expand(self, item: dict, args: dict) -> str:
        uri = item["uri"]
        for key, value in args.items():
            uri = uri.replace("{" + key + "}", quote(value, safe=""))
        if "{" in uri or "}" in uri:
            raise ShellError("INVALID_ARGUMENT", "Only simple URI template variables are supported")
        return uri
