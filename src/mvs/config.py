import math
import re
import sys
from pathlib import Path

import yaml

from mvs.domain.models import ServerConfig
from mvs.domain.native import NativeCommand, NativeImplementation


def validate_configs(configs: list[ServerConfig]) -> dict[str, ServerConfig]:
    result = {}
    for config in configs:
        if type(config.enabled) is not bool:
            raise ValueError("enabled 必须是布尔值")
        if type(config.max_concurrency) is not int or not 1 <= config.max_concurrency <= 64:
            raise ValueError("max_concurrency 必须为1到64的整数")
        if any(
            not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
            for value in [
                config.connect_timeout_seconds,
                config.discovery_timeout_seconds,
                config.call_timeout_seconds,
                config.refresh_ttl_seconds,
            ]
        ):
            raise ValueError("超时和刷新间隔必须为有限正数")
        if (
            not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", config.server_id)
            or config.server_id in {"mcp", "os", "results", "workspace"}
            or config.server_id in result
        ):
            raise ValueError("Invalid, reserved, or duplicate server alias")
        if config.transport not in {"stdio", "streamable_http", "native"}:
            raise ValueError("Unsupported transport")
        if (
            config.max_concurrency < 1
            or min(
                config.connect_timeout_seconds,
                config.discovery_timeout_seconds,
                config.call_timeout_seconds,
            )
            <= 0
        ):
            raise ValueError("Invalid server limits")
        if config.transport == "stdio" and not config.command:
            raise ValueError("stdio requires a trusted executable")
        if config.transport == "native":
            from mvs.infrastructure.native.bindings import validate_command

            if config.command or config.args or config.url or config.env_refs:
                raise ValueError("原生命令组的程序/环境必须写在每个命令的 implementations 中")
            names = set()
            for command in config.native_commands:
                validate_command(command)
                if command.name in names:
                    raise ValueError("原生命令名称重复")
                names.add(command.name)
        elif config.native_commands:
            raise ValueError("native_commands 只能用于 native 类型")
        result[config.server_id] = config
    return result


def load_config(path: str) -> dict[str, ServerConfig]:
    """Administrator-only file, never called with agent input."""
    content = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return parse_config(content)


def parse_config(content: dict) -> dict[str, ServerConfig]:
    """解析管理员提供的配置对象；不启动进程或网络连接。"""
    if (
        not isinstance(content, dict)
        or set(content) != {"servers"}
        or not isinstance(content["servers"], list)
    ):
        raise ValueError("配置必须仅包含 servers 列表")
    configs = []
    for raw in content["servers"]:
        if not isinstance(raw, dict):
            raise ValueError("每个服务必须是配置对象")
        raw = dict(raw)
        raw["server_id"] = raw.pop("id")
        if raw.get("command") == "python":
            raw["command"] = sys.executable
        for key in (
            "args",
            "allowed_tools",
            "approval_tools",
            "allowed_resources",
            "allowed_prompts",
            "http_allowed_hosts",
        ):
            if not isinstance(raw.get(key, []), (list, tuple)) or not all(
                isinstance(item, str) for item in raw.get(key, [])
            ):
                raise ValueError(f"{key} 必须是字符串数组")
            raw[key] = tuple(raw.get(key, ()))
        native = []
        for item in raw.get("native_commands", []):
            item = dict(item)
            implementations = {}
            for platform, values in item["implementations"].items():
                values = dict(values)
                values["argv"] = tuple(values.get("argv", ()))
                implementations[platform] = NativeImplementation(**values)
            item["implementations"] = implementations
            item["path_roots"] = {
                key: tuple(roots) for key, roots in item.get("path_roots", {}).items()
            }
            item["allow_option_values"] = tuple(item.get("allow_option_values", ()))
            native.append(NativeCommand(**item))
        raw["native_commands"] = tuple(native)
        configs.append(ServerConfig(**raw))
    return validate_configs(configs)
