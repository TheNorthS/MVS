import pytest

from mvs.core.schema_adapter import SchemaAdapter
from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig, ToolDescriptor
from mvs.parser.parser import CommandParser
from mvs.security.policy import PolicyEngine, Principal


def adapt(command, properties, **extra):
    return SchemaAdapter().adapt(
        CommandParser().parse("run x " + command).options,
        {"type": "object", "properties": properties, **extra},
    )


@pytest.mark.parametrize(
    "schema,text,value",
    [
        ({"type": "integer"}, "-3", -3),
        ({"type": "number"}, "0.75", 0.75),
        ({"type": "boolean"}, "false", False),
        ({"type": "boolean"}, "", True),
        ({"type": "string"}, "null", "null"),
        ({"type": "null"}, "null", None),
        ({"type": "object"}, "'{\"x\":[1,2]}'", {"x": [1, 2]}),
        ({"type": "array"}, "'[1,2]'", [1, 2]),
        ({"enum": ["a", "b"]}, "a", "a"),
    ],
)
def test_conversions(schema, text, value):
    assert adapt("--value " + text, {"value": schema}) == {"value": value}


@pytest.mark.parametrize(
    "command,props,extra",
    [
        ("--n", {"n": {"type": "integer"}}, {}),
        ("--n x", {"n": {"type": "integer"}}, {}),
        ("--n NaN", {"n": {"type": "number"}}, {}),
        ("--n Infinity", {"n": {"type": "number"}}, {}),
        ("--b yes", {"b": {"type": "boolean"}}, {}),
        ("--n 0", {"n": {"type": "integer", "minimum": 1}}, {}),
        ("--x 1", {}, {"additionalProperties": False}),
        ("", {"x": {"type": "string"}}, {"required": ["x"]}),
        ("--x c", {"x": {"enum": ["a", "b"]}}, {}),
        ("--x 123", {"x": {"type": ["integer", "string"]}}, {}),
        ("--x 1", {"x": {"oneOf": [{"type": "integer"}, {"type": "number"}]}}, {}),
        ('--params-json "{}" --x 1', {}, {}),
        ('--params-json "[]"', {}, {}),
        ('--params-json \'{"x":1,"x":2}\'', {}, {}),
    ],
)
def test_invalid(command, props, extra):
    with pytest.raises(ShellError) as exc:
        adapt(command, props, **extra)
    assert exc.value.code == "INVALID_ARGUMENT"


def test_ref_union_defaults_and_recursion():
    assert adapt(
        "--n 4", {"n": {"$ref": "#/$defs/int"}}, **{"$defs": {"int": {"type": "integer"}}}
    ) == {"n": 4}
    assert adapt('--params-json \'{"n":"123"}\'', {"n": {"type": ["string", "integer"]}}) == {
        "n": "123"
    }
    assert adapt("", {"n": {"type": "integer", "default": 5}}) == {}
    for schema in [{"$ref": "https://invalid/schema"}, {"$ref": "#"}]:
        with pytest.raises(ShellError):
            SchemaAdapter().adapt((), schema)


def test_policy_default_deny_and_untrusted_annotations():
    config = ServerConfig(
        "demo", command="python", allowed_tools=("add",), approval_tools=("write",)
    )
    policy = PolicyEngine({"demo": config}, {("tenant", "alice"): {"demo"}})
    alice = Principal("alice", "tenant")
    stranger = Principal("other", "tenant")
    tool = ToolDescriptor("demo", "erase", None, "", {}, None, {"read_only_hint": True}, "1", 0)
    assert policy.authorize_call(alice, tool, {}).outcome == "deny"
    assert policy.authorize_discovery(stranger, "demo").outcome == "deny"
    assert policy.authorize_result(alice, ("tenant", "alice")).outcome == "allow"
    assert policy.authorize_result(stranger, ("tenant", "alice")).outcome == "deny"
