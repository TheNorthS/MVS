import json
import re
from typing import Any

from mvs.core.schema_adapter import parse_json
from mvs.domain.errors import ShellError
from mvs.pipeline.types import PipeKind, PipeValue, pipe_value


def check_limits(value: PipeValue) -> None:
    if len(json.dumps(value.value).encode()) > 4 * 1024 * 1024:
        raise ShellError("LIMIT_EXCEEDED", "Pipeline exceeds 4 MiB")
    if isinstance(value.value, list) and len(value.value) > 10000:
        raise ShellError("LIMIT_EXCEEDED", "Pipeline exceeds 10000 records")


def field(row: object, path: str) -> Any:
    value = row
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ShellError("INVALID_ARGUMENT", "Projection field not found", path=path)
        value = value[key]
    return value


def transform(value: PipeValue, verb: str, args: tuple[str, ...]) -> PipeValue:
    result: Any
    check_limits(value)
    data = value.value
    if value.kind in {PipeKind.ERROR, PipeKind.BINARY_REF}:
        raise ShellError("INVALID_ARGUMENT", "Pipeline source is not transformable")
    if verb == "head":
        if len(args) != 2 or args[0] != "-n" or not args[1].isdigit():
            raise ShellError("SYNTAX_ERROR", "head -n <0..1000>")
        n = int(args[1])
        if n > 1000:
            raise ShellError("LIMIT_EXCEEDED", "head limit is 1000")
        if value.kind == PipeKind.TEXT:
            result = "\n".join(data.splitlines()[:n])
        elif value.kind == PipeKind.TABLE:
            result = data[:n]
        else:
            raise ShellError("INVALID_ARGUMENT", "head requires table or text")
    elif value.kind not in {PipeKind.JSON, PipeKind.TABLE}:
        raise ShellError("INVALID_ARGUMENT", "Transform requires JSON or table")
    elif verb == "count" and not args:
        if not isinstance(data, (dict, list)):
            raise ShellError("INVALID_ARGUMENT", "count requires object or array")
        result = len(data)
    elif verb == "select" and len(args) == 1:
        paths = args[0].split(",")
        if len(paths) > 32 or any(not re.fullmatch(r"[\w.-]+(?:\[\]\.[\w.-]+)?", p) for p in paths):
            raise ShellError("INVALID_ARGUMENT", "Invalid projection path")
        if any("[]." in path for path in paths):
            prefixes = {path.split("[].")[0] for path in paths}
            if len(prefixes) != 1 or not all("[]." in path for path in paths):
                raise ShellError("INVALID_ARGUMENT", "Projection must use one common array prefix")
            data = field(data, prefixes.pop())
            paths = [path.split("[].")[1] for path in paths]
        if len({path.rsplit(".", 1)[-1] for path in paths}) != len(paths):
            raise ShellError("INVALID_ARGUMENT", "Duplicate projected field name")

        def project(row: object) -> dict:
            return {path.rsplit(".", 1)[-1]: field(row, path) for path in paths}

        result = [project(row) for row in data] if isinstance(data, list) else project(data)
    elif verb == "sort" and len(args) in (1, 2) and (len(args) == 1 or args[1] == "--desc"):
        if not isinstance(data, list):
            raise ShellError("INVALID_ARGUMENT", "sort requires array")
        try:
            result = sorted(data, key=lambda row: field(row, args[0]), reverse=len(args) == 2)
        except TypeError:
            raise ShellError(
                "INVALID_ARGUMENT", "sort fields must have comparable scalar types"
            ) from None
    elif verb == "where" and len(args) == 3:
        if not isinstance(data, list) or args[1] not in {"eq", "ne", "lt", "le", "gt", "ge"}:
            raise ShellError("INVALID_ARGUMENT", "where <field> <eq|ne|lt|le|gt|ge> <JSON value>")
        expected = parse_json(args[2])

        def matches(row: object) -> bool:
            actual = field(row, args[0])
            try:
                match args[1]:
                    case "eq":
                        return actual == expected
                    case "ne":
                        return actual != expected
                    case "lt":
                        return actual < expected
                    case "le":
                        return actual <= expected
                    case "gt":
                        return actual > expected
                    case _:
                        return actual >= expected
            except TypeError:
                raise ShellError(
                    "INVALID_ARGUMENT", "where values have incompatible types"
                ) from None

        result = [row for row in data if matches(row)]
    else:
        raise ShellError("SYNTAX_ERROR", "Invalid transform arguments")
    output = pipe_value(result, value.source_ref)
    check_limits(output)
    return output
