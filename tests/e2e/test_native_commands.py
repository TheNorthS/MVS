import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from mvs.api.app import create_app
from mvs.config import load_config
from mvs.domain.models import ServerConfig
from mvs.domain.native import NativeCommand, NativeImplementation
from mvs.infrastructure.observability import PrometheusTelemetry
from mvs.security.policy import Principal
from mvs.services.shell_service import ShellService

FIXTURE = Path("tests/fixtures/native_program.py").resolve()


def command(tmp_path, name="echo", mode="echo", **kwargs):
    implementation = NativeImplementation(
        sys.executable, str(tmp_path), (str(FIXTURE), mode, {"param": "value"})
    )
    return NativeCommand(
        name,
        "测试用管理员固定程序",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        {sys.platform: implementation},
        **kwargs,
    )


def configs(*commands):
    return {
        "localos": ServerConfig(
            "localos",
            transport="native",
            native_commands=commands,
            allowed_tools=tuple(c.name for c in commands),
        )
    }


async def test_native_mixed_syntax_data_policy_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("MVS_UNRELATED_SECRET", "must-not-be-inherited")
    cs = configs(command(tmp_path))
    telemetry = PrometheusTelemetry(set(cs))
    service = ShellService(cs, storage_root=tmp_path / "store", telemetry=telemetry)
    await service.start()
    session = service.sessions.create("local", "local")
    stranger = service.sessions.create("stranger", "tenant")
    try:
        assert (await service.execute("ls /os", session)).data == ["localos/"]
        assert (await service.execute("ls /mcp", session)).data == []
        payload = "空格 hello; $(whoami) `id` & | >"
        params = json.dumps({"value": payload}, ensure_ascii=False)
        first = await service.execute(
            f"run /os/localos/tools/echo --params-json '{params}'", session
        )
        second = await service.execute(f"/os/localos/tools/echo --params-json '{params}'", session)
        assert first.status == second.status == "success", first
        assert first.data == second.data
        value = json.loads(first.data["stdout"])
        assert value["value"] == payload
        assert value["secret"] is None
        assert Path(value["cwd"]) == tmp_path
        assert first.data["exit_code"] == 0 and first.result_ref
        assert (await service.execute("cd /os/localos/tools", session)).status == "success"
        assert (await service.execute("./echo --value good | select exit_code", session)).data == {
            "exit_code": 0
        }
        assert (await service.execute("help echo", session)).data["backend"] == "native"
        assert (await service.execute("ls /os", stranger)).data == []
        assert (await service.execute("/os/localos/tools/echo --value x", stranger)).error[
            "code"
        ] == "NOT_FOUND"
        assert (await service.execute("run /mcp/localos/tools/echo --value x", session)).error[
            "code"
        ] == "NOT_FOUND"
        assert (await service.execute("run /bin/sh --value x", session)).error[
            "code"
        ] == "NOT_FOUND"
        assert (await service.execute("./echo --value --bad", session)).status == "error"
        assert (
            telemetry.registry.get_sample_value(
                "mvs_native_command_calls_total",
                {"server": "localos", "tool": "echo", "status": "success"},
            )
            == 3
        )
        assert (
            telemetry.registry.get_sample_value(
                "mvs_tool_calls_total", {"server": "localos", "tool": "echo", "status": "success"}
            )
            is None
        )
    finally:
        await service.close()


async def test_native_exit_output_limit_timeout_cancel(tmp_path):
    cs = configs(
        command(tmp_path, "bad", "fail"),
        command(tmp_path, "flood", "flood", max_output_bytes=1024),
        command(tmp_path, "slow", "sleep", timeout_seconds=0.3),
    )
    service = ShellService(cs, storage_root=tmp_path / "store")
    await service.start()
    session = service.sessions.create("local", "local")
    try:
        bad = await service.execute("/os/localos/tools/bad --value x | count", session)
        assert bad.error["code"] == "COMMAND_FAILED", bad
        assert bad.data["exit_code"] == 7 and bad.result_ref
        saved = await service.results.get(bad.result_ref, ("local", "local"))
        assert saved.structured_data["stderr"].splitlines() == ["failure detail"]
        assert bad.exit_code == 7
        flood = await service.execute("/os/localos/tools/flood --value x", session)
        assert flood.error["code"] == "RESULT_TOO_LARGE", flood
        slow = await service.execute("/os/localos/tools/slow --value x", session)
        assert slow.error["code"] == "TIMEOUT_UNCERTAIN", slow
        task = asyncio.create_task(service.execute("/os/localos/tools/slow --value x", session))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.manager.connections["localos"].active_count == 0
    finally:
        await service.close()


async def test_path_boundary_approval_and_disabled(tmp_path):
    cmd = command(tmp_path, path_roots={"value": (str(tmp_path),)})
    cs = configs(cmd, replace(cmd, name="disabled", enabled=False))
    service = ShellService(cs, storage_root=tmp_path / "store")
    await service.start()
    session = service.sessions.create("local", "local")
    try:
        outside = (tmp_path.parent / "outside.txt").as_posix()
        result = await service.execute(f"/os/localos/tools/echo --value '{outside}'", session)
        assert result.error["code"] == "POLICY_DENIED"
        assert (await service.execute("tools localos", session)).data == ["/os/localos/tools/echo"]
        service.policy.configs["localos"] = replace(cs["localos"], approval_tools=("echo",))
        result = await service.execute("/os/localos/tools/echo --value x", session)
        assert result.status == "approval_required"
        assert not (tmp_path / "outside.txt").exists()
    finally:
        await service.close()


async def test_api_native_and_config_loading(tmp_path):
    import yaml

    cs = configs(command(tmp_path))
    from dataclasses import asdict

    raw = asdict(cs["localos"])
    raw["id"] = raw.pop("server_id")
    file = tmp_path / "servers.yaml"
    file.write_text(yaml.safe_dump({"servers": [raw]}), encoding="utf-8")
    loaded = load_config(str(file))
    token = "native-test-" + "x" * 24
    app = create_app(
        loaded, {token: Principal("u", "t")}, {("t", "u"): {"localos"}}, tmp_path / "api"
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + token},
        ) as client:
            session = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
            response = (
                await client.post(
                    "/api/v1/shell/execute",
                    json={"session_id": session, "command": "/os/localos/tools/echo --value api"},
                )
            ).json()
            assert response["status"] == "success", response
            assert json.loads(response["data"]["stdout"])["value"] == "api"
