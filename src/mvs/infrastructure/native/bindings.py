"""把管理员命令定义绑定为当前平台的固定 argv，不做 Shell 文本插值。"""

import codecs
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

from mvs.core.schema_adapter import SchemaAdapter, check_schema
from mvs.domain.errors import ShellError
from mvs.domain.native import NativeCommand, NativeImplementation

PLATFORMS = {"linux", "darwin", "win32"}


def validate_command(command: NativeCommand) -> None:
    if command.sandbox_image and not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_./:@-]{0,255}", command.sandbox_image
    ):
        raise ValueError("容器镜像引用格式无效")
    if command.memory_limit_mb is not None and not 32 <= command.memory_limit_mb <= 65536:
        raise ValueError("内存限制必须为32..65536 MiB")
    if command.cpu_time_seconds is not None and not 1 <= command.cpu_time_seconds <= 3600:
        raise ValueError("CPU时间限制必须为1..3600秒")
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.-]{0,63}", command.name):
        raise ValueError("原生命令名格式错误")
    check_schema(command.input_schema)
    schema = command.input_schema
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValueError("原生命令 Schema 必须声明 object 和 additionalProperties: false")
    if not math.isfinite(command.timeout_seconds) or not 0 < command.timeout_seconds <= 3600:
        raise ValueError("原生命令超时必须为 0..3600 秒")
    if not 1 <= command.max_output_bytes <= 1024 * 1024:
        raise ValueError("原生命令输出上限必须为 1..1048576 字节")
    if not command.implementations or not set(command.implementations) <= PLATFORMS:
        raise ValueError("支持的平台键为 linux、darwin、win32")
    properties = schema.get("properties", {})
    if not set(command.path_roots) <= properties.keys():
        raise ValueError("路径约束必须对应已声明参数")
    if not set(command.allow_option_values) <= properties.keys():
        raise ValueError("选项值例外必须对应已声明参数")
    for key, roots in command.path_roots.items():
        if properties[key].get("type") != "string" or not roots:
            raise ValueError("路径参数必须为字符串，且至少配置一个根目录")
    for platform, impl in command.implementations.items():
        path_type = PureWindowsPath if platform == "win32" else PurePosixPath
        for path, kind in (
            (impl.executable, PurePosixPath if command.sandbox_image else path_type),
            (impl.cwd, path_type),
        ):
            if not kind(path).is_absolute() or "\x00" in path:
                raise ValueError("程序和工作目录必须是管理员固定的绝对路径")
        if (
            not command.sandbox_image
            and platform == "win32"
            and path_type(impl.executable).suffix.lower() != ".exe"
        ):
            raise ValueError("Windows 直接执行入口必须为 .exe，不能隐式执行批处理")
        # 已知命令解释器只能接受管理员固定脚本；不能把模型字符串绑定为执行源码。
        shell_name = path_type(impl.executable).stem.lower()
        if (shell_name.startswith("python") or shell_name in {"node", "ruby", "perl"}) and any(
            isinstance(token, dict) for token in impl.argv
        ):
            script = impl.argv[0] if impl.argv else None
            if not isinstance(script, str) or not path_type(script).is_absolute():
                raise ValueError("通用解释器动态参数仅可传给管理员固定的绝对脚本路径")
        if shell_name in {"sh", "bash", "zsh", "dash", "ksh", "cmd", "powershell", "pwsh"}:
            argv = list(impl.argv)
            if shell_name in {"powershell", "pwsh"}:
                try:
                    index = next(
                        i
                        for i, value in enumerate(argv)
                        if isinstance(value, str) and value.lower() == "-file"
                    )
                except StopIteration:
                    raise ValueError("PowerShell 必须用 -File 调用管理员固定脚本") from None
                if any(
                    not isinstance(v, str) or v.lower() not in {"-noprofile", "-noninteractive"}
                    for v in argv[:index]
                ):
                    raise ValueError("PowerShell -File 前仅允许 -NoProfile 与 -NonInteractive")
            elif shell_name == "cmd":
                raise ValueError("不暴露 cmd /c；请把固定操作封装为管理员 PowerShell 脚本")
            else:
                index = -1
            script_index = index + 1
            script = argv[script_index] if len(argv) > script_index else None
            if not isinstance(script, str) or not path_type(script).is_absolute():
                raise ValueError("解释器脚本路径必须是管理员固定的绝对路径")
        codecs.lookup(impl.encoding)
        if len(impl.argv) > 128:
            raise ValueError("固定 argv 最多128项")
        referenced = set()
        for token in impl.argv:
            if isinstance(token, str):
                if "\x00" in token:
                    raise ValueError("固定参数不能包含 NUL")
            elif (
                isinstance(token, dict) and set(token) == {"param"} and token["param"] in properties
            ):
                referenced.add(token["param"])
            else:
                raise ValueError("argv 仅接受字面字符串或 {param: 参数名}")
        if referenced != set(properties):
            raise ValueError("每个声明参数必须有 argv 绑定，禁止静默忽略参数")
        if referenced - set(schema.get("required", [])):
            raise ValueError("动态 argv 参数必须声明 required；默认值不会自动注入")
        for key, value in impl.env_refs.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or not value:
                raise ValueError("环境变量引用格式错误")


def implementation(command: NativeCommand) -> NativeImplementation:
    impl = command.implementations.get(sys.platform)
    if impl is None:
        raise ShellError("COMMAND_UNAVAILABLE", "该命令未配置当前操作系统的实现")
    return impl


def bind(command: NativeCommand, arguments: dict) -> tuple[NativeImplementation, list[str]]:
    validate_command(command)
    SchemaAdapter().validate(arguments, command.input_schema)
    impl = implementation(command)
    executable, cwd = Path(impl.executable), Path(impl.cwd)
    if (not command.sandbox_image and not executable.is_file()) or not cwd.is_dir():
        raise ShellError("COMMAND_UNAVAILABLE", "配置的程序或工作目录不存在")
    values = {}
    for name, value in arguments.items():
        if name in command.path_roots:
            requested = Path(value)
            resolved = (requested if requested.is_absolute() else cwd / requested).resolve()
            roots = [Path(root) for root in command.path_roots[name]]
            if any(not root.is_absolute() for root in roots):
                raise ShellError("POLICY_DENIED", "当前平台的路径根目录配置必须为绝对路径")
            if not any(resolved.is_relative_to(root.resolve()) for root in roots):
                raise ShellError("POLICY_DENIED", "命令路径参数超出管理员允许范围")
            value = str(resolved)
        text = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, allow_nan=False)
        )
        if "\x00" in text or len(text.encode()) > 16384:
            raise ShellError("INVALID_ARGUMENT", "原生命令参数包含 NUL 或超过字节上限")
        if (
            isinstance(value, str)
            and text.startswith("-")
            and name not in command.allow_option_values
        ):
            raise ShellError("INVALID_ARGUMENT", "字符串参数不能隐式变成程序选项")
        values[name] = text
    return impl, [
        token if isinstance(token, str) else values[token["param"]] for token in impl.argv
    ]
