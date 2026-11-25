from mvs.config import load_config
from mvs.security.audit import redact
from mvs.services.shell_service import ShellService


async def test_untrusted_principal_and_call_quota():
    service = ShellService(load_config("configs/servers.example.yaml"))
    stranger = service.sessions.create("stranger", "local")
    local = service.sessions.create("local", "local")
    await service.start()
    try:
        assert (await service.execute("ls /mcp", stranger)).data == []
        assert (await service.execute("/mcp/demo/tools/add --a 1 --b 2", stranger)).error[
            "code"
        ] == "NOT_FOUND"
        local.max_calls = 0
        assert (await service.execute("/mcp/demo/tools/add --a 1 --b 2", local)).error[
            "code"
        ] == "LIMIT_EXCEEDED"
        assert local.calls == 0
        service.policy.grants.clear()
        assert (await service.execute("ls /mcp/demo", local)).error["code"] == "NOT_FOUND"
    finally:
        await service.close()


def test_redaction():
    assert redact({"password": "secret", "nested": [{"api_key": "secret"}], "a": 2}) == {
        "password": "[REDACTED]",
        "nested": [{"api_key": "[REDACTED]"}],
        "a": 2,
    }
