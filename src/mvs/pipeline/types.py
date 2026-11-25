from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PipeKind(StrEnum):
    JSON = "json"
    TABLE = "table"
    TEXT = "text"
    BINARY_REF = "binary_ref"
    ERROR = "error"


@dataclass(frozen=True)
class PipeValue:
    kind: PipeKind
    value: Any
    source_ref: str | None = None


def pipe_value(data: Any, source_ref: str | None = None) -> PipeValue:
    kind = (
        PipeKind.TEXT
        if isinstance(data, str)
        else (PipeKind.TABLE if isinstance(data, list) else PipeKind.JSON)
    )
    return PipeValue(kind, data, source_ref)
