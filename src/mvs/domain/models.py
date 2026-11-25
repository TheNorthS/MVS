from dataclasses import dataclass, field
from typing import Any

from mvs.domain.native import NativeCommand


@dataclass(frozen=True)
class ServerConfig:
    server_id: str
    transport: str = "stdio"
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    env_refs: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    trust_level: str = "restricted"
    allowed_tools: tuple[str, ...] = ()
    approval_tools: tuple[str, ...] = ()
    allowed_resources: tuple[str, ...] = ()
    allowed_prompts: tuple[str, ...] = ()
    http_allowed_hosts: tuple[str, ...] = ()
    http_allow_private: bool = False
    auth_ref: str | None = None
    refresh_ttl_seconds: float = 60
    # SDK v2 的旧协议探测本身最多等待 10 秒，还需留出进程启动与回退握手时间。
    connect_timeout_seconds: float = 30
    discovery_timeout_seconds: float = 10
    call_timeout_seconds: float = 15
    max_concurrency: int = 2
    native_commands: tuple[NativeCommand, ...] = ()


@dataclass(frozen=True)
class ToolDescriptor:
    server_id: str
    name: str
    title: str | None
    description: str
    input_schema: dict
    output_schema: dict | None
    annotations: dict
    revision: str
    discovered_at: float
    backend: str = "mcp"


@dataclass(frozen=True)
class ToolInvocation:
    server_id: str
    tool_name: str
    arguments: dict
    registry_revision: str
    request_id: str


@dataclass(frozen=True)
class ResultEnvelope:
    invocation_id: str
    server_id: str
    tool_name: str
    success: bool
    structured_data: Any
    text_blocks: tuple[str, ...] = ()
    asset_refs: tuple[str, ...] = ()
    error_code: str | None = None
    duration_ms: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class SessionContext:
    session_id: str
    principal_id: str
    tenant_id: str
    cwd: str = "/"
    created_at: float = 0
    expires_at: float = 0
    max_calls: int = 100
    calls: int = 0


@dataclass
class ShellResponse:
    request_id: str
    session_id: str
    status: str = "success"
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    data: Any = None
    result_ref: str | None = None
    truncated: bool = False
    duration_ms: int = 0
    error: dict | None = None
