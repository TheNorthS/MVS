from pathlib import Path

import pytest

from mvs.domain.errors import ShellError
from mvs.domain.models import ResultEnvelope
from mvs.infrastructure.storage.result_store import ResultStore
from mvs.pipeline.planner import PipelineParser
from mvs.pipeline.transforms import transform
from mvs.pipeline.types import pipe_value


async def test_owner_ttl_pagination_and_quota(tmp_path: Path):
    store = ResultStore(tmp_path)
    result = ResultEnvelope("req", "s", "t", True, list(range(10)))
    ref = await store.put(result, ("tenant", "a"))
    assert await store.slice(ref, ("tenant", "a"), 2, 3) == [2, 3, 4]
    for owner in [("tenant", "b"), ("other", "a")]:
        with pytest.raises(ShellError):
            await store.get(ref, owner)
    expired = await store.put(result, ("tenant", "a"), ttl_s=-1)
    with pytest.raises(ShellError):
        await store.get(expired, ("tenant", "a"))
    assert await store.delete_expired() == 1
    store.quota = 1
    with pytest.raises(ShellError):
        await store.put(result, ("tenant", "a"))
    store.close()


def test_projection_sort_where_head_count():
    value = pipe_value({"items": [{"name": "a", "stars": 1}, {"name": "b", "stars": 3}]})
    value = transform(value, "select", ("items[].name,items[].stars",))
    value = transform(value, "where", ("stars", "gt", "0"))
    value = transform(value, "sort", ("stars", "--desc"))
    value = transform(value, "head", ("-n", "1"))
    assert value.value == [{"name": "b", "stars": 3}]
    assert transform(value, "count", ()).value == 1
    assert transform(pipe_value("a\nb"), "head", ("-n", "1")).value == "a"


@pytest.mark.parametrize(
    "command",
    ["run a | run b", "run a || count", "run a |", "pwd | count", "run a | python", "head -n 2"],
)
def test_invalid_pipeline(command):
    with pytest.raises(ShellError):
        PipelineParser().parse(command)


def test_literal_pipe():
    ast = PipelineParser().parse('run echo --text "a|b" | head -n 1')
    assert ast.stages[0].options[0].value == "a|b"
