from mvs.domain.errors import ShellError
from mvs.parser.ast import CommandAST
from mvs.parser.lexer import Token, tokenize
from mvs.parser.parser import CommandParser, parse_options

TRANSFORMS = {"select", "where", "sort", "head", "count"}


class PipelineParser(CommandParser):
    def parse(self, source: str) -> CommandAST:
        tokens = tokenize(source, pipelines=True)
        parts: list[list[Token]] = [[]]
        for token in tokens:
            if token.operator:
                parts.append([])
            else:
                parts[-1].append(token)
        if len(parts) > 8:
            raise ShellError("LIMIT_EXCEEDED", "At most 8 pipeline stages")
        stages = []
        for i, part in enumerate(parts):
            if not part:
                raise ShellError("SYNTAX_ERROR", "Empty pipeline stage")
            verb = part[0].text
            if i and verb not in TRANSFORMS:
                raise ShellError(
                    "UNSUPPORTED_SYNTAX", "Pipeline tails must be read-only transforms"
                )
            if verb in TRANSFORMS:
                stage = CommandAST("builtin", verb, args=tuple(t.text for t in part[1:]))
            elif verb in {"cat", "refresh", "prompt", "read"}:
                if len(part) < 2:
                    raise ShellError("SYNTAX_ERROR", "Command requires a target")
                stage = CommandAST("builtin", verb, part[1].text, parse_options(part[2:]))
            else:
                stage = self.command(part, source)
            stages.append(stage)
        if len(stages) == 1:
            if stages[0].verb in TRANSFORMS:
                raise ShellError("SYNTAX_ERROR", "Transform needs a pipeline source")
            return stages[0]
        if stages[0].kind != "tool" and stages[0].verb != "cat":
            raise ShellError("UNSUPPORTED_SYNTAX", "Pipeline source must be tool or cat")
        return CommandAST("pipeline", "pipeline", source=source, stages=tuple(stages))
