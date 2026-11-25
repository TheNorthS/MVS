from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class RawOption:
    name: str
    value: str | None
    position: int = field(compare=False)


@dataclass(frozen=True)
class CommandAST:
    kind: Literal["builtin", "tool", "pipeline"]
    verb: str
    target: str | None = None
    options: tuple[RawOption, ...] = ()
    source: str = field(default="", compare=False)
    args: tuple[str, ...] = ()
    stages: tuple["CommandAST", ...] = ()
