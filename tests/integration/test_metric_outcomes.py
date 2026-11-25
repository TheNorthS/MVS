import asyncio
from dataclasses import replace

import pytest

from mvs.config import load_config
from mvs.domain.errors import ShellError
from mvs.infrastructure.observability import PrometheusTelemetry
from mvs.services.shell_service import ShellService


def sample(observer, metric, **labels):
    return observer.registry.get_sample_value(metric, labels) or 0


async def test_errors_approval_and_queue_revocation(tmp_path):
    configs = load_config("configs/servers.example.yaml")
    observer = PrometheusTelemetry(set(configs))
    service = ShellService(configs, storage_root=tmp_path, telemetry=observer)
    session = service.sessions.create("local", "local")
    await service.start()
    try:
        original = service.manager.call_tool

        async def business_error(*args):
            return {"is_error": True, "structured_content": None, "content": []}

        service.manager.call_tool = business_error
        reply = await service.execute("/mcp/demo/tools/add --a 1 --b 2", session)
        assert reply.error["code"] == "TOOL_EXECUTION_FAILED"
        assert (
            sample(observer, "mvs_tool_calls_total", server="demo", tool="add", status="error") == 1
        )
        assert sample(observer, "mvs_result_bytes_total", server="demo") == 0

        async def wrong_output(*args):
            return {"is_error": False, "structured_content": {"result": "bad"}, "content": []}

        service.manager.call_tool = wrong_output
        reply = await service.execute("/mcp/demo/tools/add --a 1 --b 2", session)
        assert reply.error["code"] == "INVALID_TOOL_OUTPUT"
        assert (
            sample(observer, "mvs_tool_calls_total", server="demo", tool="add", status="error") == 2
        )
        service.manager.call_tool = original
        service.policy.configs["demo"] = replace(configs["demo"], approval_tools=("add",))
        reply = await service.execute("/mcp/demo/tools/add --a 1 --b 2", session)
        assert reply.status == "approval_required"
        assert (
            sample(observer, "mvs_policy_denials_total", server="demo", reason="approval_required")
            == 1
        )
        service.policy.configs["demo"] = replace(configs["demo"], approval_tools=())
        semaphore = service.executor.semaphores["demo"]
        await semaphore.acquire()
        await semaphore.acquire()
        task = asyncio.create_task(service.execute("/mcp/demo/tools/add --a 1 --b 2", session))
        await asyncio.sleep(0.01)
        service.policy.grants.clear()
        semaphore.release()
        semaphore.release()
        assert (await task).error["code"] == "POLICY_DENIED"
        assert (
            sample(
                observer, "mvs_policy_denials_total", server="demo", reason="authorization_changed"
            )
            == 1
        )
        assert (
            sample(observer, "mvs_tool_calls_total", server="demo", tool="add", status="error") == 2
        )
    finally:
        await service.close()


async def test_missing_result_is_not_owner_denial_and_storage_failure_no_bytes(tmp_path):
    configs = load_config("configs/servers.example.yaml")
    observer = PrometheusTelemetry(set(configs))
    service = ShellService(configs, storage_root=tmp_path, telemetry=observer)
    session = service.sessions.create("local", "local")
    await service.start()
    try:
        reply = await service.execute("cat /results/missing", session)
        assert reply.error["code"] == "NOT_FOUND"
        assert (
            sample(
                observer, "mvs_policy_denials_total", server="unknown", reason="result_not_owned"
            )
            == 0
        )
        service.results.quota = 1
        reply = await service.execute("/mcp/demo/tools/add --a 1 --b 2", session)
        assert reply.error["code"] == "RESULT_TOO_LARGE"
        assert sample(observer, "mvs_result_bytes_total", server="demo") == 0
        assert (
            sample(observer, "mvs_tool_calls_total", server="demo", tool="add", status="success")
            == 1
        )

        async def fail(*args, **kwargs):
            raise ShellError("LIMIT_EXCEEDED", "fixture")

        service.manager.list_tools = fail
        with pytest.raises(ShellError):
            await service.registry.refresh("demo")
        assert sample(observer, "mvs_registry_refresh_total", server="demo", status="error") == 1
    finally:
        await service.close()
