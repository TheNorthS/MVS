import pytest

from mvs.domain.errors import ShellError
from mvs.parser.parser import CommandParser

parser = CommandParser()


def test_mixed_equivalence_and_positions():
    a = parser.parse("run /mcp/demo/tools/add --a -3 --b=5")
    b = parser.parse("/mcp/demo/tools/add --a -3 --b=5")
    assert a == b
    assert a.options[0].value == "-3"
    assert a.options[0].position == 24
    assert parser.parse("./add --a 1").target == "./add"


@pytest.mark.parametrize(
    "text,value",
    [
        ('"hello world"', "hello world"),
        ("'{\"x\":1}'", '{"x":1}'),
        ("'$(whoami); `ls` > & | $HOME *'", "$(whoami); `ls` > & | $HOME *"),
        ('""', ""),
        ("hello\\ world", "hello world"),
        ('"a\\nb"', "a\nb"),
    ],
)
def test_data(text, value):
    assert parser.parse("run echo --text " + text).options[0].value == value


@pytest.mark.parametrize(
    "command,code",
    [
        ("run add --a 1 --a=2", "INVALID_ARGUMENT"),
        ("add --a 1", "UNKNOWN_COMMAND"),
        ("bash", "UNKNOWN_COMMAND"),
        ("run", "SYNTAX_ERROR"),
        ("run --a 1", "SYNTAX_ERROR"),
        ('run echo --text "oops', "SYNTAX_ERROR"),
        ('run echo --text "\\q"', "SYNTAX_ERROR"),
        ("run echo --text a\\q", "SYNTAX_ERROR"),
        ('run echo --text "\x00"', "SYNTAX_ERROR"),
        ("run add -- 2", "INVALID_ARGUMENT"),
        ("pwd more", "SYNTAX_ERROR"),
        ("cd", "SYNTAX_ERROR"),
        ("", "SYNTAX_ERROR"),
        ("run x --=2", "SYNTAX_ERROR"),
        ("x" * 16385, "LIMIT_EXCEEDED"),
        ("run x " + "a " * 257, "LIMIT_EXCEEDED"),
    ],
)
def test_errors(command, code):
    with pytest.raises(ShellError) as exc:
        parser.parse(command)
    assert exc.value.code == code


@pytest.mark.parametrize(
    "operator", ["|", ";", "&&", "||", ">", "<", "&", "$(whoami)", "`whoami`", "$HOME", "*.py"]
)
def test_no_os_semantics(operator):
    with pytest.raises(ShellError, match="disabled"):
        parser.parse("run echo --text " + operator)


def test_boolean_and_missing_value_preserved_for_schema():
    assert parser.parse("run x --flag").options[0].value is None
    assert parser.parse("run x --").options == ()
