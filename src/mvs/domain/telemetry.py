"""Dependency-free observation contract; the local core defaults to a no-op observer."""

from contextlib import AbstractContextManager, nullcontext
from typing import Any


class Telemetry:
    def trace_id(self) -> str | None:
        return None

    def annotate(self, **attributes: Any) -> None:
        return None

    def span(self, name: str, **attributes: Any) -> AbstractContextManager:
        return nullcontext()

    def shell_finished(self, command: str, status: str, seconds: float) -> None:
        return None

    def tool_finished(self, server: str, tool: str, status: str, seconds: float) -> None:
        return None

    def native_finished(self, server: str, tool: str, status: str, seconds: float) -> None:
        return None

    def registry_finished(self, server: str, status: str, seconds: float) -> None:
        return None

    def result_stored(self, server: str, size: int) -> None:
        return None

    def policy_denied(self, server: str, reason: str) -> None:
        return None
