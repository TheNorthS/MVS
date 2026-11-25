from mvs.config import load_config
from mvs.core.vfs import encode_name
from mvs.services.shell_service import ShellService


async def test_real_pipeline_results_and_catalog(tmp_path):
    service = ShellService(load_config("configs/servers.example.yaml"), storage_root=tmp_path)
    session = service.sessions.create("local", "local")
    await service.start()
    try:
        result = await service.execute(
            "run /mcp/demo/tools/add --a 1 --b 2 | select result", session
        )
        assert result.status == "success", result
        assert result.data == {"result": 3}
        assert session.calls == 1
        count = await service.execute(f"cat {result.result_ref} | count", session)
        assert count.data == 1
        assert session.calls == 1
        bad = await service.execute("run /mcp/demo/tools/add --a bad --b 2 | count", session)
        assert bad.error["code"] == "INVALID_ARGUMENT"
        assert session.calls == 1
        listing = await service.execute("ls /mcp/demo/resources", session)
        assert listing.data == [encode_name("demo://info")]
        resource = await service.execute(
            "cat /mcp/demo/resources/" + encode_name("demo://info"), session
        )
        assert resource.stdout == "MVS demo resource", resource
        template = "/mcp/demo/resource_templates/" + encode_name("demo://greeting/{name}")
        resource = await service.execute(f"read {template} --name Alice", session)
        assert resource.stdout == "Hello Alice", resource
        prompt = await service.execute("prompt /mcp/demo/prompts/welcome --name Alice", session)
        assert "Welcome Alice" in prompt.stdout
        assert prompt.data["untrusted"] is True
        assert (await service.execute("refresh demo", session)).status == "success"
        text = "x" * 10000
        large = await service.execute("run /mcp/demo/tools/echo --text " + text, session)
        assert large.truncated
        assert len(large.stdout.encode()) == 8192
        stored = await service.results.get(large.result_ref, ("local", "local"))
        assert stored.structured_data == {"result": text}
    finally:
        await service.close()
