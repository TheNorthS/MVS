import random
import string

import pytest

from mvs.core.schema_adapter import SchemaAdapter
from mvs.domain.errors import ShellError
from mvs.pipeline.planner import PipelineParser
from mvs.pipeline.transforms import transform
from mvs.pipeline.types import pipe_value


def test_bounded_parser_fuzz():
    rng = random.Random(42)
    parser = PipelineParser()
    for _ in range(1000):
        command = "".join(rng.choice(string.printable) for _ in range(rng.randrange(200)))
        try:
            parser.parse(command)
        except ShellError:
            continue


def test_depth_and_table_limits():
    value = {}
    for _ in range(40):
        value = {"child": value}
    with pytest.raises(ShellError):
        SchemaAdapter().validate(value, {})
    with pytest.raises(ShellError):
        transform(pipe_value(list(range(10001))), "count", ())
    with pytest.raises(ShellError):
        transform(pipe_value("text"), "count", ())
    with pytest.raises(ShellError):
        transform(pipe_value([{"a": 1}, {"a": "x"}]), "sort", ("a",))
    with pytest.raises(ShellError):
        transform(pipe_value([{"a": 1}]), "where", ("a", "gt", '"x"'))
