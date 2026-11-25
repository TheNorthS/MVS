import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from examples.deploy_api import create_app_from_env
from examples.gpt_agent import AgentError, run_agent, validate_gateway_url
from mvs.config import load_config
from mvs.domain.models import ServerConfig
from mvs.services.shell_service import ShellService


def test_deployment_rejects_unknown_grants_and_shared_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("MVS_CONFIG", "configs/servers.example.yaml")
    monkeypatch.setenv("MVS_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("MVS_ALLOWED_SERVERS", "missing")
    with pytest.raises(ValueError, match="服务器列表"):
        create_app_from_env()
    monkeypatch.setenv("MVS_ALLOWED_SERVERS", "demo")
    monkeypatch.setenv("MVS_AGENT_TOKEN", "a" * 32)
    monkeypatch.setenv("MVS_ADMIN_TOKEN", "a" * 32)
    with pytest.raises(ValueError, match="不同令牌"):
        create_app_from_env()


async def test_agent_api_real_mcp_loop_and_cleanup(monkeypatch, tmp_path):
    monkeypatch.setenv("MVS_CONFIG", "configs/servers.example.yaml")
    monkeypatch.setenv("MVS_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("MVS_ALLOWED_SERVERS", "demo")
    monkeypatch.setenv("MVS_AGENT_TOKEN", "a" * 32)
    monkeypatch.setenv("MVS_ADMIN_TOKEN", "b" * 32)
    app = create_app_from_env()

    class Model:
        n = 0

        async def complete(self, instructions, history, tools):
            self.n += 1
            assert len(tools) == 1 and tools[0]["name"] == "virtual_shell"
            if self.n == 1:
                output = [
                    {
                        "type": "function_call",
                        "call_id": "call1",
                        "name": "virtual_shell",
                        "arguments": json.dumps({"command": "run /mcp/demo/tools/add --a 2 --b 3"}),
                    }
                ]
            else:
                result = json.loads(history[-1]["output"])["untrusted_tool_data"]
                assert result["data"] == {"result": 5}
                output = [
                    {"type": "message", "content": [{"type": "output_text", "text": "结果为5"}]}
                ]
            return {
                "output": output,
                "status": "completed",
                "model": "test-fixture",
                "usage": {"total_tokens": 20},
            }

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + "a" * 32},
        ) as client:
            result = await run_agent("计算2+3", Model(), client)
            assert result["status"] == "completed" and result["answer"] == "结果为5"
            assert result["session_closed"] and result["observed_tokens"] == 40
            assert (await client.get("/metrics")).status_code == 403
            assert (
                await client.post(
                    "/api/v1/shell/execute",
                    json={"session_id": result["session_id"], "command": "pwd"},
                )
            ).status_code == 404


@pytest.mark.parametrize(
    "status,code", [("approval_required", "APPROVAL_REQUIRED"), ("error", "TIMEOUT_UNCERTAIN")]
)
async def test_agent_stops_instead_of_retrying_uncertain_calls(status, code):
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(200, json={"deleted": True})
        if request.url.path.endswith("/sessions"):
            return httpx.Response(200, json={"session_id": "s"})
        return httpx.Response(200, json={"status": status, "error": {"code": code}, "stderr": code})

    class Model:
        async def complete(self, *args):
            return {
                "output": [
                    {
                        "type": "function_call",
                        "name": "virtual_shell",
                        "call_id": "1",
                        "arguments": '{"command":"run tool"}',
                    }
                ]
            }

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    ) as client:
        result = await run_agent("task", Model(), client)
    assert result["status"] == "execution_stopped" and result["model_rounds"] == 1
    assert result["session_closed"] and not result["usage_complete"]
    assert seen == [
        ("POST", "/api/v1/sessions"),
        ("POST", "/api/v1/shell/execute"),
        ("DELETE", "/api/v1/sessions/s"),
    ]


def test_gateway_url_boundary():
    for url in ["https://mvs.example.com", "http://127.0.0.1:8080"]:
        validate_gateway_url(url)
    for url in ["http://mvs.example.com", "https://secret@mvs.example.com", "file:///tmp/a"]:
        with pytest.raises(AgentError):
            validate_gateway_url(url)
    configs = load_config("configs/servers.linux.example.yaml")
    assert configs["gitrepo"].allowed_tools == (
        "git_status",
        "git_log",
        "git_show",
        "git_diff_unstaged",
        "git_diff_staged",
    )


GIT_PYTHON = Path(
    os.environ.get(
        "MVS_GIT_MCP_PYTHON",
        ".tools/git-mcp/Scripts/python.exe"
        if sys.platform == "win32"
        else ".tools/git-mcp/bin/python",
    )
).absolute()


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / "note.txt").write_text("真实 Git MCP 测试\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "note.txt"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=MVS Test",
            "-c",
            "user.email=mvs-test@example.invalid",
            "commit",
            "-m",
            "tutorial fixture",
        ],
        check=True,
        capture_output=True,
    )
    return repo


@pytest.mark.skipif(not GIT_PYTHON.exists(), reason="需要教程的隔离 Git MCP 环境")
async def test_official_git_mcp_readonly_tools(tmp_path, git_repo):
    repo = git_repo
    configs = {
        "gitrepo": ServerConfig(
            "gitrepo",
            command=str(GIT_PYTHON),
            args=("-m", "mcp_server_git", "--repository", repo.as_posix()),
            allowed_tools=("git_status", "git_log"),
        )
    }
    service = ShellService(configs, storage_root=tmp_path / "results")
    await service.start()
    try:
        session = service.sessions.create("local", "local")
        listing = await service.execute("tools gitrepo", session)
        assert listing.data == ["/mcp/gitrepo/tools/git_log", "/mcp/gitrepo/tools/git_status"]
        result = await service.execute(
            "run /mcp/gitrepo/tools/git_status --params-json "
            + "'"
            + json.dumps({"repo_path": repo.as_posix()})
            + "'",
            session,
        )
        assert result.status == "success", result
        log = await service.execute(
            "run /mcp/gitrepo/tools/git_log --params-json "
            + "'"
            + json.dumps({"repo_path": repo.as_posix(), "max_count": 1})
            + "'",
            session,
        )
        assert log.status == "success" and "tutorial fixture" in log.stdout
        denied = await service.execute("help /mcp/gitrepo/tools/git_commit", session)
        assert denied.error["code"] == "NOT_FOUND"
    finally:
        await service.close()
