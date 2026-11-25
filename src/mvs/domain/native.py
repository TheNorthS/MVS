"""管理员定义的原生命令契约，不接受模型提交程序路径或整段脚本。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NativeImplementation:
    executable: str
    cwd: str
    argv: tuple[str | dict[str, str], ...] = ()
    env_refs: dict[str, str] = field(default_factory=dict)
    encoding: str = "utf-8"


@dataclass(frozen=True)
class NativeCommand:
    name: str
    description: str
    input_schema: dict
    implementations: dict[str, NativeImplementation]
    enabled: bool = True
    timeout_seconds: float = 10
    max_output_bytes: int = 262144
    path_roots: dict[str, tuple[str, ...]] = field(default_factory=dict)
    allow_option_values: tuple[str, ...] = ()
    memory_limit_mb: int | None = None
    cpu_time_seconds: int | None = None
    sandbox_image: str | None = None
    sandbox_network: bool = False
