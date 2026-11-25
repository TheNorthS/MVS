from dataclasses import dataclass

from mvs.domain.errors import ShellError


@dataclass(frozen=True)
class Token:
    text: str
    position: int
    operator: bool = False


def tokenize(source: str, *, pipelines: bool = False) -> list[Token]:
    if len(source.encode("utf-8")) > 16384:
        raise ShellError("LIMIT_EXCEEDED", "Command exceeds 16384 UTF-8 bytes")
    tokens: list[Token] = []
    i = 0
    while i < len(source):
        if source[i].isspace():
            i += 1
            continue
        start = i
        chars: list[str] = []
        quote: str | None = None
        while i < len(source):
            char = source[i]
            if ord(char) < 32 and char not in "\t\n":
                raise ShellError("SYNTAX_ERROR", "Control character in command")
            if quote:
                if char == quote:
                    quote = None
                elif char == "\\" and quote == '"':
                    i += 1
                    if i >= len(source) or source[i] not in '\\"nt':
                        raise ShellError("SYNTAX_ERROR", "Invalid quoted escape")
                    chars.append({"n": "\n", "t": "\t"}.get(source[i], source[i]))
                else:
                    chars.append(char)
            elif char.isspace():
                break
            elif char in "\"'":
                quote = char
            elif char == "\\":
                i += 1
                if i >= len(source) or source[i] not in " \\\"'":
                    raise ShellError("SYNTAX_ERROR", "Invalid escape")
                chars.append(source[i])
            elif char == "|" and pipelines and source[i : i + 2] != "||":
                if i == start:
                    tokens.append(Token("|", i, True))
                    i += 1
                    start = i
                break
            elif char in ";&|<>`$*?()":
                raise ShellError("UNSUPPORTED_SYNTAX", "Shell expansion/operator is disabled")
            else:
                chars.append(char)
            i += 1
        if quote:
            raise ShellError("SYNTAX_ERROR", "Unclosed quote")
        if i > start:
            tokens.append(Token("".join(chars), start))
        if len(tokens) > 256:
            raise ShellError("LIMIT_EXCEEDED", "Too many tokens")
    return tokens
