"""最终用户的初始化、诊断和控制台启动命令。"""

import argparse
import getpass
import json
import os
import secrets
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from mvs.config import load_config, parse_config
from mvs.management.lock import InstanceLock
from mvs.management.store import StateStore, data_directory, token_hash


def handle(args: argparse.Namespace) -> int:
    root = Path(args.home).expanduser().resolve() if args.home else data_directory()
    if args.mode == "backup":
        from mvs.management.backup import backup, restore

        password = getpass.getpass("备份密码（至少12字符）：")
        if args.action == "create":
            backup(root, Path(args.path), password)
        else:
            restore(Path(args.path), root, password)
        print("备份操作完成")
        return 0
    if args.mode == "service":
        from mvs.management.service_install import install_service

        install_service(root, args.action == "uninstall")
        print("服务注册操作完成")
        return 0
    if args.mode == "update":
        from mvs.management.updates import check_release, install_release, rollback_release

        os.environ["MVS_DEFER_UPDATE"] = "1"
        if args.action == "status":
            print((root / "releases/update-status.json").read_text(encoding="utf-8"))
            return 0
        if args.action == "rollback":
            rollback_release(root)
        else:
            if not args.url:
                raise ValueError("请用 --url 指定HTTPS发布清单地址")
            manifest = check_release(args.url)
            if args.action == "check":
                print(json.dumps(manifest, ensure_ascii=False, indent=2))
            else:
                print(install_release(root, manifest))
        return 0
    if args.mode == "repair":
        from mvs.infrastructure.storage.result_store import ResultStore

        lock = InstanceLock(root)
        lock.acquire()
        try:
            if os.environ.get("MVS_POSTGRES_DSN"):
                import asyncio

                from mvs.infrastructure.storage.postgres_results import PostgresResultStore

                remote = PostgresResultStore(
                    os.environ["MVS_POSTGRES_DSN"],
                    bucket=os.environ.get("MVS_S3_BUCKET"),
                    endpoint_url=os.environ.get("MVS_S3_ENDPOINT"),
                )
                try:
                    print(json.dumps(asyncio.run(remote.repair()), ensure_ascii=False))
                finally:
                    remote.close()
                return 0
            results = ResultStore(root / "results")
            try:
                print(json.dumps(results.repair(), ensure_ascii=False))
            finally:
                results.close()
        finally:
            lock.release()
        return 0
    if args.mode == "serve":
        try:
            import uvicorn

            from mvs.management.app import create_console
        except ImportError:
            print("请安装 console 可选依赖", file=sys.stderr)
            return 1
        if args.host not in {"127.0.0.1", "localhost", "::1"}:
            print("远程访问请通过HTTPS反向代理或SSH隧道，本命令只监听回环地址。", file=sys.stderr)
            return 1
        app = create_console(root)
        url = f"http://127.0.0.1:{args.port}"
        print(
            f'MVS 管理后台：{url}\n数据目录：{root}\n查看登录令牌：mvs token show --home "{root}"'
        )
        if args.open_browser:
            timer = threading.Timer(1.5, webbrowser.open, args=(url,))
            timer.daemon = True
            timer.start()
        uvicorn.run(app, host=args.host, port=args.port, workers=1)
        return 0
    store = StateStore(root)
    try:
        if args.mode == "init":
            token = store.initialize(not args.empty)
            print("初始化完成。" if token else "实例已初始化；保留现有配置和令牌。")
            print(
                f'数据目录：{root}\n下一步：mvs serve --home "{root}" --open\n'
                f'查看管理员令牌：mvs token show --home "{root}"'
            )
            return 0
        if args.mode == "token":
            if args.action == "reset":
                lock = InstanceLock(root)
                lock.acquire()
                try:
                    revision, state = store.read()
                    user = next((u for u in state["users"] if u["id"] == args.user), None)
                    if user is None or "admin" not in user["roles"]:
                        raise ValueError("只能重置已存在的管理员令牌")
                    value = secrets.token_urlsafe(32)
                    user.update(enabled=True, token_hash=token_hash(value))
                    store.save(revision, state)
                    (root / "admin-token").write_text(value, encoding="utf-8")
                    print("管理员令牌已重置。用 mvs token show 查看新令牌，再启动服务。")
                    return 0
                finally:
                    lock.release()
            path = root / "admin-token"
            if not path.exists():
                raise ValueError("本机引导令牌文件不存在")
            value = path.read_text(encoding="utf-8")
            if store.authenticate(value) is None:
                raise ValueError("引导令牌已失效；请使用后台轮换时保存的新令牌")
            print(value)
            return 0
        if args.mode == "config":
            import yaml

            if args.action == "export":
                target = Path(args.path)
                with target.open("x", encoding="utf-8") as file:
                    yaml.safe_dump(
                        {"servers": store.read()[1]["servers"]}, file, allow_unicode=True
                    )
                print(f"已导出服务配置：{target}（不含用户令牌或托管凭证）")
                return 0
            lock = InstanceLock(root)
            lock.acquire()
            try:
                load_config(args.path)
                raw = yaml.safe_load(Path(args.path).read_text(encoding="utf-8"))
                revision, state = store.read()
                merged = {s["id"]: s for s in state["servers"]}
                merged.update({s["id"]: s for s in raw["servers"]})
                state["servers"] = list(merged.values())
                for user in state["users"]:
                    if "admin" in user["roles"]:
                        user["servers"] = list(merged)
                store.save(revision, state)
                print("配置已校验并合并。普通用户需要单独授权，启动服务后在后台管理。")
                return 0
            finally:
                lock.release()
        if args.mode == "doctor":
            checks = {
                "python": sys.version.split()[0],
                "home": str(root),
                "initialized": store.initialized(),
                "ui_bundled": (Path(__file__).resolve().parents[1] / "web/index.html").exists(),
            }
            if store.initialized():
                revision, state = store.read()
                configs = parse_config({"servers": state["servers"]})
                checks.update(
                    revision=revision, configured_servers=len(configs), users=len(state["users"])
                )
            print(json.dumps(checks, ensure_ascii=False, indent=2))
            return 0 if checks["initialized"] and checks["ui_bundled"] else 1
    finally:
        store.close()
    return 1


def add_commands(sub: Any) -> None:
    svc = sub.add_parser("service", help="安装/卸载当前用户的后台服务")
    svc.add_argument("action", choices=["install", "uninstall"])
    svc.add_argument("--home")
    upd = sub.add_parser("update", help="检查、安装可信发布清单或回滚")
    upd.add_argument("action", choices=["check", "install", "rollback", "status"])
    upd.add_argument("--url")
    upd.add_argument("--home")
    repair = sub.add_parser("repair", help="离线检查结果对象一致性")
    repair.add_argument("--home")
    back = sub.add_parser("backup", help="加密备份与离线恢复整个实例")
    back.add_argument("action", choices=["create", "restore"])
    back.add_argument("path")
    back.add_argument("--home")
    init = sub.add_parser("init", help="初始化本机实例（幂等）")
    init.add_argument("--home")
    init.add_argument("--empty", action="store_true", help="不创建演示服务")
    serve = sub.add_parser("serve", help="启动API与可视化管理后台")
    serve.add_argument("--home")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--open", dest="open_browser", action="store_true")
    doctor = sub.add_parser("doctor", help="检查本机安装与配置")
    doctor.add_argument("--home")
    token = sub.add_parser("token", help="查看本机初始管理员令牌")
    token.add_argument("action", choices=["show", "reset"])
    token.add_argument("--home")
    token.add_argument("--user", default="admin", help="离线重置的管理员ID")
    config = sub.add_parser("config", help="离线导入或导出服务配置")
    config.add_argument("action", choices=["import", "export"])
    config.add_argument("path")
    config.add_argument("--home")
