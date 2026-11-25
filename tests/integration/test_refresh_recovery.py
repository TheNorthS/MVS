import asyncio
from dataclasses import replace

import pytest

from mvs.config import load_config
from mvs.domain.errors import ShellError
from mvs.domain.models import ToolInvocation
from mvs.services.shell_service import ShellService


async def test_ttl_reconnect_and_schema_refresh(tmp_path):
    configs = load_config("configs/servers.example.yaml")
    configs["demo"] = replace(configs["demo"], refresh_ttl_seconds=0.01)
    service = ShellService(configs, storage_root=tmp_path)
    await service.start()
    try:
        old = service.registry.get("demo", "add")
        await service.manager.disconnect("demo")
        service.registry.status["demo"] = "offline"
        service.last_refresh["demo"] = 0
        await service.refresh_due()
        assert service.registry.status["demo"] == "online"
        session = service.sessions.create("local", "local")
        assert (await service.execute("/mcp/demo/tools/add --a 1 --b 2", session)).data == {
            "result": 3
        }

        # Publish changed remote schema as one atomic discovery response.
        async def changed(*args, **kwargs):
            return [
                dict(
                    name="add",
                    title=None,
                    description="",
                    annotations={},
                    output_schema=None,
                    input_schema={
                        "type": "object",
                        "properties": {"a": {"type": "string"}},
                        "additionalProperties": False,
                    },
                )
            ]

        service.manager.list_tools = changed
        await service.registry.refresh("demo")
        with pytest.raises(ShellError) as exc:
            await service.executor.invoke(ToolInvocation("demo", "add", {}, old.revision, "req"))
        assert exc.value.code == "TOOL_CHANGED"
        bad = await service.execute("/mcp/demo/tools/add --a 1 --b 2", session)
        assert bad.error["code"] == "INVALID_ARGUMENT"
    finally:
        await service.close()


async def test_revocation_while_queued(tmp_path):
    service = ShellService(load_config("configs/servers.example.yaml"), storage_root=tmp_path)
    await service.start()
    try:
        semaphore = service.executor.semaphores["demo"]
        await semaphore.acquire()
        await semaphore.acquire()
        session = service.sessions.create("local", "local")
        task = asyncio.create_task(service.execute("/mcp/demo/tools/add --a 1 --b 2", session))
        await asyncio.sleep(0.01)
        service.policy.grants.clear()
        semaphore.release()
        semaphore.release()
        assert (await task).error["code"] == "POLICY_DENIED"
    finally:
        await service.close()
