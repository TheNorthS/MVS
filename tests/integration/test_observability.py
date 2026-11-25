import asyncio
from dataclasses import replace

from mvs.config import load_config
from mvs.infrastructure.observability import PrometheusTelemetry
from mvs.security.policy import PolicyEngine
from mvs.services.shell_service import ShellService


def metric(observer, name, **labels):
    return observer.registry.get_sample_value(name, labels) or 0


async def test_metrics_from_real_service(tmp_path):
    configs = load_config("configs/servers.example.yaml")
    observer = PrometheusTelemetry(set(configs))
    policy = PolicyEngine(configs, {("local", "local"): {"demo"}})
    service = ShellService(configs, policy, storage_root=tmp_path, telemetry=observer)
    session = service.sessions.create("local", "local")
    stranger = service.sessions.create("secret-person", "secret-tenant")
    await service.start()
    try:
        result = await service.execute("/mcp/demo/tools/add --a 1 --b 2", session)
        assert result.data == {"result": 3}
        assert (
            metric(observer, "mvs_tool_calls_total", server="demo", tool="add", status="success")
            == 1
        )
        assert metric(observer, "mvs_tool_duration_seconds_count", server="demo", tool="add") == 1
        size = service.results.db.execute("SELECT SUM(size) FROM results").fetchone()[0]
        assert metric(observer, "mvs_result_bytes_total", server="demo") == size
        assert metric(observer, "mvs_registry_refresh_total", server="demo", status="success") == 1
        await service.execute("cat " + result.result_ref, stranger)
        await service.execute("/mcp/demo/tools/add --a 1 --b 2", stranger)
        policy.configs["demo"] = replace(configs["demo"], allowed_tools=())
        await service.execute("/mcp/demo/tools/add --a 1 --b 2", session)
        assert (
            metric(observer, "mvs_policy_denials_total", server="demo", reason="server_not_granted")
            == 1
        )
        assert (
            metric(observer, "mvs_policy_denials_total", server="demo", reason="tool_not_allowed")
            == 1
        )
        assert (
            metric(
                observer, "mvs_policy_denials_total", server="unknown", reason="result_not_owned"
            )
            == 1
        )
        exported = observer.export().decode()
        for secret in ["secret-person", "secret-tenant", session.session_id, result.result_ref]:
            assert secret not in exported
        # Discovery visibility checks must not turn ordinary ls into a denial storm.
        before = metric(
            observer, "mvs_policy_denials_total", server="demo", reason="server_not_granted"
        )
        await service.execute("ls /mcp", stranger)
        assert (
            metric(observer, "mvs_policy_denials_total", server="demo", reason="server_not_granted")
            == before
        )
    finally:
        await service.close()


async def test_timeout_cancel_failure_counted_once(tmp_path):
    configs = load_config("configs/servers.example.yaml")
    configs["demo"] = replace(configs["demo"], call_timeout_seconds=0.02)
    observer = PrometheusTelemetry(set(configs))
    service = ShellService(configs, storage_root=tmp_path, telemetry=observer)
    await service.start()
    try:

        async def slow(*args):
            await asyncio.sleep(10)

        service.manager.call_tool = slow
        session = service.sessions.create("local", "local")
        response = await service.execute("/mcp/demo/tools/add --a 1 --b 2", session)
        assert response.error["code"] == "TIMEOUT_UNCERTAIN"
        assert (
            metric(observer, "mvs_tool_calls_total", server="demo", tool="add", status="timeout")
            == 1
        )
        task = asyncio.create_task(service.execute("/mcp/demo/tools/add --a 1 --b 2", session))
        await asyncio.sleep(0.005)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert metric(observer, "mvs_shell_requests_total", status="cancelled", command="run") == 1
        assert (
            metric(observer, "mvs_tool_calls_total", server="demo", tool="add", status="cancelled")
            == 1
        )

        async def failure(*args, **kwargs):
            raise OSError("private-credential")

        service.manager.list_tools = failure
        try:
            await service.registry.refresh("demo")
        except Exception:
            assert (
                metric(observer, "mvs_registry_refresh_total", server="demo", status="error") == 1
            )
        assert "private-credential" not in observer.export().decode()
    finally:
        await service.close()
