import asyncio
from dataclasses import replace

import pytest

from mvs.core.registry import Registry
from mvs.core.result_normalizer import ResultNormalizer, preview
from mvs.domain.errors import ShellError
from mvs.domain.models import ServerConfig, ToolDescriptor, ToolInvocation
from mvs.infrastructure.mcp.executor import MCPExecutor


class Manager:
    def __init__(self, timeout=1):
        self.configs = {
            "demo": ServerConfig(
                "demo", command="python", max_concurrency=2, call_timeout_seconds=timeout
            )
        }
        self.active = self.peak = self.calls = 0
        self.delay = 0.01

    async def call_tool(self, *args):
        self.calls += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.delay)
            return {"is_error": False, "structured_content": {"result": 5}, "content": []}
        finally:
            self.active -= 1


def executor(timeout=1):
    manager = Manager(timeout)
    registry = Registry(manager.configs, manager)
    registry.status["demo"] = "online"
    registry._tools["demo", "add"] = ToolDescriptor("demo", "add", None, "", {}, None, {}, "1", 0)
    return MCPExecutor(manager, registry), manager


async def test_concurrency_revision_and_no_retry():
    exe, manager = executor()
    inv = ToolInvocation("demo", "add", {}, "1", "req")
    results = await asyncio.gather(*(exe.invoke(replace(inv, request_id=str(i))) for i in range(8)))
    assert manager.peak == 2
    assert len({result.invocation_id for result in results}) == 8
    with pytest.raises(ShellError) as exc:
        await exe.invoke(replace(inv, registry_revision="old"))
    assert exc.value.code == "TOOL_CHANGED"
    assert manager.calls == 8
    exe, manager = executor(0.001)
    with pytest.raises(ShellError) as exc:
        await exe.invoke(inv)
    assert exc.value.code == "TIMEOUT_UNCERTAIN"
    assert manager.calls == 1
    assert manager.active == 0


def test_results_media_errors_output_and_utf8():
    normalizer = ResultNormalizer()
    inv = ToolInvocation("demo", "x", {}, "1", "req")
    raw = {
        "is_error": False,
        "structured_content": {"result": 1},
        "content": [
            {"type": "text", "text": "你好"},
            {"type": "image", "data": "PRIVATE_BASE64", "mime_type": "image/png"},
        ],
    }
    result = normalizer.normalize(raw, inv, None, 1)
    assert result.text_blocks == ("你好",)
    assert result.metadata["asset_types"] == ["image"]
    assert "PRIVATE_BASE64" not in str(result)
    assert normalizer.assets[result.asset_refs[0]]["data"] == "PRIVATE_BASE64"
    assert preview("你好", 4) == ("你", True)
    assert (
        normalizer.normalize({**raw, "is_error": True}, inv, None, 1).error_code
        == "TOOL_EXECUTION_FAILED"
    )
    assert normalizer.normalize(raw, inv, {"type": "string"}, 1).error_code == "INVALID_TOOL_OUTPUT"
