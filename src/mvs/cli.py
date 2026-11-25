import argparse
import asyncio
import json
import logging
from dataclasses import asdict

from mvs.config import load_config
from mvs.services.shell_service import ShellService


async def run_cli(config: str, mode: str, command: list[str], as_json: bool) -> int:
    service = ShellService(load_config(config))
    session = service.sessions.create("local", "local")
    await service.start()
    try:
        while True:
            if mode == "exec":
                text = " ".join(command[1:] if command[:1] == ["--"] else command)
            else:
                try:
                    text = await asyncio.to_thread(input, f"mvs:{session.cwd}> ")
                except EOFError:
                    return 0
            response = await service.execute(text, session)
            print(
                json.dumps(asdict(response), ensure_ascii=False)
                if as_json
                else response.stderr or response.stdout
            )
            if mode == "exec" or response.data == {"exit": True}:
                return response.exit_code
    finally:
        await service.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP 与原生命令受管入口；不执行任意 Shell 文本")
    parser.add_argument("--config", default="configs/servers.example.yaml")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--audit", action="store_true")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("repl")
    sub.add_parser("exec").add_argument("command", nargs=argparse.REMAINDER)
    from mvs.management.commands import add_commands, handle

    add_commands(sub)
    args = parser.parse_args()
    if args.mode in {
        "init",
        "serve",
        "doctor",
        "token",
        "config",
        "backup",
        "service",
        "update",
        "repair",
    }:
        try:
            raise SystemExit(handle(args))
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
    if args.audit:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        code = asyncio.run(run_cli(args.config, args.mode, getattr(args, "command", []), args.json))
    except KeyboardInterrupt:
        code = 130
    raise SystemExit(code)
