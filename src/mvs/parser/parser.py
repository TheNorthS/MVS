import re

from mvs.domain.errors import ShellError
from mvs.parser.ast import CommandAST, RawOption
from mvs.parser.lexer import Token, tokenize

BUILTINS = {
    "pwd": (0, 0),
    "servers": (0, 0),
    "exit": (0, 0),
    "ls": (0, 1),
    "cd": (1, 1),
    "help": (0, 1),
    "tools": (0, 1),
}


def parse_options(tokens: list[Token]) -> tuple[RawOption, ...]:
    result = []
    names: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.text == "--":
            if i == len(tokens) - 1:
                break
            raise ShellError("INVALID_ARGUMENT", "Tool positional arguments are not supported")
        if not token.text.startswith("--"):
            raise ShellError("INVALID_ARGUMENT", "Tool positional arguments are not supported")
        name, sep, value = token.text[2:].partition("=")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", name):
            raise ShellError("SYNTAX_ERROR", "Invalid option name")
        if name in names:
            raise ShellError("INVALID_ARGUMENT", "Duplicate option", option=name)
        names.add(name)
        raw: str | None = value if sep else None
        if not sep and i + 1 < len(tokens) and not tokens[i + 1].text.startswith("--"):
            i += 1
            raw = tokens[i].text
        result.append(RawOption(name, raw, token.position))
        i += 1
    return tuple(result)


class CommandParser:
    def parse(self, source: str) -> CommandAST:
        return self.command(tokenize(source), source)

    def command(self, tokens: list[Token], source: str = "") -> CommandAST:
        if not tokens:
            raise ShellError("SYNTAX_ERROR", "Empty command")
        verb = tokens[0].text
        if verb in BUILTINS:
            lo, hi = BUILTINS[verb]
            if not lo <= len(tokens) - 1 <= hi:
                raise ShellError("SYNTAX_ERROR", "Incorrect builtin argument count")
            return CommandAST(
                "builtin", verb, tokens[1].text if len(tokens) > 1 else None, source=source
            )
        if verb == "run":
            if len(tokens) < 2 or tokens[1].text.startswith("--"):
                raise ShellError("SYNTAX_ERROR", "run requires a tool path")
            target, remaining = tokens[1].text, tokens[2:]
        elif verb.startswith(("/", "./")):
            target, remaining = verb, tokens[1:]
        else:
            raise ShellError("UNKNOWN_COMMAND", "Unknown command; use help")
        return CommandAST("tool", "run", target, parse_options(remaining), source)
