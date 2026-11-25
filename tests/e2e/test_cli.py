import json

from mvs.cli import run_cli


async def test_actual_cli_json_and_repl(capsys, monkeypatch):
    assert (
        await run_cli(
            "configs/servers.example.yaml", "exec", ["--", "/mcp/demo/tools/add --a 2 --b 3"], True
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["data"] == {"result": 5}
    commands = iter(["pwd", "cd /mcp/demo/tools", "run add --a -3 --b 5", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(commands))
    assert await run_cli("configs/servers.example.yaml", "repl", [], False) == 0
    assert "2" in capsys.readouterr().out.splitlines()
