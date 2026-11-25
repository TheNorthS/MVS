"""Optional Prometheus/OTel observer. Labels never contain principal/query/result IDs."""

from contextlib import AbstractContextManager
from typing import Any

from opentelemetry import trace
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from mvs.domain.telemetry import Telemetry

COMMANDS = frozenset(
    {
        "pwd",
        "ls",
        "cd",
        "help",
        "servers",
        "tools",
        "run",
        "exit",
        "pipeline",
        "cat",
        "read",
        "prompt",
        "refresh",
    }
)
REASONS = frozenset(
    {
        "server_not_granted",
        "tool_not_allowed",
        "approval_required",
        "authorization_changed",
        "catalog_not_allowed",
        "result_not_owned",
        "admin_required",
    }
)
BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)


class PrometheusTelemetry(Telemetry):
    def __init__(self, servers: set[str], registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()
        self.servers = frozenset(servers)
        self.tracer = trace.get_tracer("mvs")
        self.requests = Counter(
            "mvs_shell_requests_total",
            "Completed shell requests",
            ["status", "command"],
            registry=self.registry,
        )
        self.shell_duration = Histogram(
            "mvs_shell_duration_seconds",
            "Shell wall time",
            ["command"],
            buckets=BUCKETS,
            registry=self.registry,
        )
        self.calls = Counter(
            "mvs_tool_calls_total",
            "Dispatched tools/call attempts",
            ["server", "tool", "status"],
            registry=self.registry,
        )
        self.native_calls = Counter(
            "mvs_native_command_calls_total",
            "原生命令后端执行尝试",
            ["server", "tool", "status"],
            registry=self.registry,
        )
        self.native_duration = Histogram(
            "mvs_native_command_duration_seconds",
            "原生命令耗时含排队",
            ["server", "tool"],
            buckets=BUCKETS,
            registry=self.registry,
        )
        self.tool_duration = Histogram(
            "mvs_tool_duration_seconds",
            "Tool wall time including queue",
            ["server", "tool"],
            buckets=BUCKETS,
            registry=self.registry,
        )
        self.refreshes = Counter(
            "mvs_registry_refresh_total",
            "Completed tool-list refresh attempts",
            ["server", "status"],
            registry=self.registry,
        )
        self.refresh_duration = Histogram(
            "mvs_registry_refresh_duration_seconds",
            "Refresh wall time",
            ["server"],
            buckets=BUCKETS,
            registry=self.registry,
        )
        self.result_bytes = Counter(
            "mvs_result_bytes_total",
            "Successfully persisted envelope/asset bytes",
            ["server"],
            registry=self.registry,
        )
        self.denials = Counter(
            "mvs_policy_denials_total",
            "Explicit authorization denials",
            ["server", "reason"],
            registry=self.registry,
        )

    def server_label(self, server: str) -> str:
        return server if server in self.servers else "unknown"

    def trace_id(self) -> str | None:
        context = trace.get_current_span().get_span_context()
        return f"{context.trace_id:032x}" if context.is_valid else None

    def annotate(self, **attributes: Any) -> None:
        trace.get_current_span().set_attributes(attributes)

    def span(self, name: str, **attributes: Any) -> AbstractContextManager:
        return self.tracer.start_as_current_span(name, attributes=attributes)

    def shell_finished(self, command: str, status: str, seconds: float) -> None:
        command = command if command in COMMANDS else "unknown"
        self.requests.labels(status, command).inc()
        self.shell_duration.labels(command).observe(seconds)

    def tool_finished(self, server: str, tool: str, status: str, seconds: float) -> None:
        # Called only after resolving a registered ToolDescriptor, never with arbitrary input.
        server = self.server_label(server)
        self.calls.labels(server, tool, status).inc()
        self.tool_duration.labels(server, tool).observe(seconds)

    def registry_finished(self, server: str, status: str, seconds: float) -> None:
        server = self.server_label(server)
        self.refreshes.labels(server, status).inc()
        self.refresh_duration.labels(server).observe(seconds)

    def native_finished(self, server: str, tool: str, status: str, seconds: float) -> None:
        server = self.server_label(server)
        self.native_calls.labels(server, tool, status).inc()
        self.native_duration.labels(server, tool).observe(seconds)

    def result_stored(self, server: str, size: int) -> None:
        self.result_bytes.labels(self.server_label(server)).inc(size)

    def policy_denied(self, server: str, reason: str) -> None:
        reason = reason if reason in REASONS else "other"
        self.denials.labels(self.server_label(server), reason).inc()

    def export(self) -> bytes:
        return generate_latest(self.registry)
