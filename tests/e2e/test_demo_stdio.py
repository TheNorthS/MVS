from mvs.config import load_config
from mvs.services.shell_service import ShellService


async def test_full_demo():
    service = ShellService(load_config("configs/servers.example.yaml"), pipelines=False)
    session = service.sessions.create("local", "local")
    await service.start()
    try:
        for command in [
            "pwd",
            "ls /mcp",
            "ls /mcp/demo/tools",
            "help /mcp/demo/tools/add",
            "servers",
            "tools demo",
        ]:
            result = await service.execute(command, session)
            assert result.status == "success", result
        a = await service.execute("run /mcp/demo/tools/add --a 10 --b 20", session)
        b = await service.execute("/mcp/demo/tools/add --a 10 --b 20", session)
        assert a.data == b.data == {"result": 30}
        assert a.request_id != b.request_id
        assert (await service.execute("cd /mcp/demo/tools", session)).status == "success"
        assert (await service.execute("run add --a -3 --b 5", session)).data == {"result": 2}
        assert (
            await service.execute('./echo --text "hello world"', session)
        ).stdout == "hello world"
        bad = await service.execute("run add --a abc --b 2", session)
        assert bad.error["code"] == "INVALID_ARGUMENT"
        bad = await service.execute("run add --a 1 --b 2 | head -n 1", session)
        assert bad.error["code"] == "UNSUPPORTED_SYNTAX"
        assert session.calls == 4
        await service.manager.disconnect("demo")
        bad = await service.execute("run add --a 1 --b 2", session)
        assert bad.error["code"] == "SERVER_OFFLINE"
    finally:
        await service.close()
