import json
import math
import re
from typing import Any

from jsonschema import ValidationError
from jsonschema.validators import validator_for

from mvs.domain.errors import ShellError
from mvs.domain.models import ToolDescriptor
from mvs.parser.ast import RawOption


def bounded(value: Any, *, depth: int = 0) -> None:
    if depth > 32:
        raise ShellError("INVALID_ARGUMENT", "JSON/Schema nesting exceeds 32 levels")
    if isinstance(value, dict):
        for child in value.values():
            bounded(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            bounded(child, depth=depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ShellError("INVALID_ARGUMENT", "Non-finite number is not allowed")
    elif isinstance(value, int) and value.bit_length() > 1024:
        raise ShellError("INVALID_ARGUMENT", "Integer exceeds supported size")


def parse_json(raw: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    try:
        if len(raw.encode()) > 65536:
            raise ValueError("JSON input too large")
        result = json.loads(raw, object_pairs_hook=pairs)
        bounded(result)
        return result
    except (ValueError, RecursionError):
        raise ShellError("INVALID_ARGUMENT", "Invalid or oversized JSON") from None


def check_schema(schema: dict) -> None:
    bounded(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "$ref" in node and not node["$ref"].startswith("#"):
                raise ShellError("INVALID_ARGUMENT", "Remote schema references are disabled")
            if "$dynamicRef" in node or "$recursiveRef" in node:
                raise ShellError("INVALID_ARGUMENT", "Dynamic references are not supported")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    validator_for(schema).check_schema(schema)


def dereference(schema: dict, root: dict) -> dict:
    seen: set[str] = set()
    while "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen or len(seen) >= 32 or not ref.startswith("#/"):
            raise ShellError("INVALID_ARGUMENT", "Cyclic or unsupported schema reference")
        seen.add(ref)
        value: Any = root
        try:
            for part in ref[2:].split("/"):
                value = value[part.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            raise ShellError("INVALID_ARGUMENT", "Schema reference not found") from None
        schema = {**value, **{key: item for key, item in schema.items() if key != "$ref"}}
    return schema


class SchemaAdapter:
    def validate(self, arguments: Any, schema: dict, max_bytes: int = 65536) -> None:
        try:
            check_schema(schema)
            bounded(arguments)
            if len(json.dumps(arguments, allow_nan=False).encode()) > max_bytes:
                raise ShellError("LIMIT_EXCEEDED", "JSON exceeds size limit")
            validator_for(schema)(schema).validate(arguments)
        except ValidationError as exc:
            path = ".".join(map(str, exc.absolute_path))
            raise ShellError(
                "INVALID_ARGUMENT",
                f"Schema validation failed ({exc.validator})",
                path=path,
                help_hint="Use help or --params-json",
            ) from None
        except (RecursionError, ValueError, KeyError) as exc:
            raise ShellError("INVALID_ARGUMENT", "Invalid schema or arguments") from exc

    def adapt(self, raw_options: tuple[RawOption, ...], input_schema: dict) -> dict:
        check_schema(input_schema)
        root = dereference(input_schema, input_schema)
        options = {option.name: option.value for option in raw_options}
        if len(options) != len(raw_options):
            raise ShellError("INVALID_ARGUMENT", "Duplicate option")
        if "params-json" in options:
            if len(options) != 1 or options["params-json"] is None:
                raise ShellError("INVALID_ARGUMENT", "--params-json must be used alone")
            arguments = parse_json(options["params-json"])
            if not isinstance(arguments, dict):
                raise ShellError("INVALID_ARGUMENT", "--params-json requires an object")
        else:
            arguments = {}
            for name, raw in options.items():
                prop = root.get("properties", {}).get(name)
                if prop is None:
                    additional = root.get("additionalProperties", True)
                    if additional is False:
                        raise ShellError("INVALID_ARGUMENT", "Unknown option", option=name)
                    prop = additional if isinstance(additional, dict) else {}
                arguments[name] = self.convert(raw, dereference(prop, input_schema))
        self.validate(arguments, input_schema)
        return arguments

    def convert(self, raw: str | None, schema: dict) -> Any:
        kind = schema.get("type")
        if isinstance(kind, list) or any(key in schema for key in ("oneOf", "anyOf", "allOf")):
            raise ShellError("INVALID_ARGUMENT", "Ambiguous type; use --params-json")
        if kind is None and ("enum" in schema or "const" in schema):
            values = schema.get("enum", [schema.get("const")])
            if all(isinstance(value, str) for value in values):
                kind = "string"
        if raw is None:
            if kind == "boolean":
                return True
            raise ShellError("INVALID_ARGUMENT", "Option requires a value")
        if kind == "string" or kind is None:
            return raw
        if kind == "boolean":
            if raw not in ("true", "false"):
                raise ShellError("INVALID_ARGUMENT", "Boolean must be true or false")
            return raw == "true"
        if kind == "integer" and not re.fullmatch(r"-?(0|[1-9][0-9]*)", raw):
            raise ShellError("INVALID_ARGUMENT", "Expected integer")
        return parse_json(raw)

    def render_help(self, descriptor: ToolDescriptor) -> str:
        schema = descriptor.input_schema
        lines = [descriptor.name, descriptor.description, "--params-json <JSON object>"]
        for name, prop in schema.get("properties", {}).items():
            required = " required" if name in schema.get("required", ()) else ""
            lines.append(f"--{name} {json.dumps(prop, ensure_ascii=False)}{required}")
        return "\n".join(lines)
