"""本机单实例管理状态：事务保存、乐观锁、令牌哈希和有界操作记录。"""

import copy
import hashlib
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema.exceptions import SchemaError

from mvs.config import parse_config
from mvs.infrastructure.storage.control_db import control_database
from mvs.security.oauth import OAuthStore
from mvs.security.rules import validate_rules
from mvs.security.vault import Vault


def data_directory() -> Path:
    if os.environ.get("MVS_HOME"):
        return Path(os.environ["MVS_HOME"]).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MVS"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/MVS"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "mvs"


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def validate_state(state: dict) -> None:
    try:
        configs = parse_config({"servers": state["servers"]})
    except SchemaError:
        raise ValueError("工具JSON Schema无效") from None
    users = state["users"]
    if not users or len(users) > 100:
        raise ValueError("用户数量必须为1到100")
    ids, hashes = set(), set()
    for user in users:
        if (
            type(user.get("rate_limit", 60)) is not int
            or not 1 <= user.get("rate_limit", 60) <= 10000
        ):
            raise ValueError("用户每分钟限流必须为1..10000整数")
        if (
            type(user["enabled"]) is not bool
            or not isinstance(user["roles"], list)
            or not isinstance(user["servers"], list)
            or not isinstance(user["name"], str)
        ):
            raise ValueError("用户启用状态、角色、授权或名称类型不正确")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", user["id"]) or user["id"] in ids:
            raise ValueError("用户ID无效或重复")
        if user["token_hash"] in hashes or not re.fullmatch("[0-9a-f]{64}", user["token_hash"]):
            raise ValueError("令牌摘要无效或重复")
        if not set(user["servers"]) <= configs.keys():
            raise ValueError("用户授权包含不存在的服务组")
        if not set(user["roles"]) <= {"admin", *state.get("roles", {}).keys()}:
            raise ValueError("用户引用了不存在的角色")
        if not user["tenant_id"] or len(user["tenant_id"]) > 64:
            raise ValueError("租户标识为空或过长")
        ids.add(user["id"])
        hashes.add(user["token_hash"])
        if not set(user.get("secret_refs", {}).values()) <= state["secrets"].keys():
            raise ValueError("用户引用了不存在的托管凭证")
        if "rules" in user:
            validate_rules(user["rules"])
    for role, rules in state.get("roles", {}).items():
        if role == "admin" or not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", role):
            raise ValueError("自定义角色名称无效")
        validate_rules(rules)
    if not any(user["enabled"] and "admin" in user["roles"] for user in users):
        raise ValueError("必须保留至少一个已启用的管理员")
    for key, value in state["secrets"].items():
        if not re.fullmatch(r"MVS_SECRET_[A-Z0-9_]{1,80}", key) or not isinstance(value, str):
            raise ValueError("托管凭证名称必须以MVS_SECRET_开头，值必须为字符串")
    model = state["model"]
    for provider in state.get("oauth", {}).values():
        OAuthStore.validate(provider)
    if model:
        if model.get("protocol", "responses") not in {"responses", "chat_completions", "anthropic"}:
            raise ValueError("不支持的模型协议")
        if len(model.get("fallbacks", [])) > 3:
            raise ValueError("最多3个备用模型")
        url = urlsplit(model["base_url"])
        if (
            url.scheme not in {"https", "http"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("模型地址必须为无内嵌凭证的HTTP(S)地址")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("远程模型接口必须使用HTTPS")
        if not model["model"] or not model["api_key_env"]:
            raise ValueError("模型ID和凭证环境变量名不能为空")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", model["api_key_env"]):
            raise ValueError("凭证引用必须是环境变量名")
        for fallback in model.get("fallbacks", []):
            validate_state({**state, "model": {**fallback, "fallbacks": []}})


class StateStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.vault = Vault(root)
        self.db = control_database(root / "control.sqlite3")
        local_database = not os.environ.get("MVS_CONTROL_POSTGRES_DSN")
        if local_database:
            self.db.execute("PRAGMA secure_delete=ON")
        if os.name != "nt" and (root / "control.sqlite3").exists():
            (root / "control.sqlite3").chmod(0o600)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), "
            "revision INTEGER, body TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, created REAL, body TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS history "
            "(revision INTEGER PRIMARY KEY, created REAL, body TEXT)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, applied REAL)"
        )
        # 事务中将已有状态迁移到加密凭证格式；读写接口对调用方不变。
        old = self.db.execute("SELECT revision,body FROM state WHERE id=1").fetchone()
        migrated = bool(old and "$encrypted" not in json.loads(old[1])["secrets"])
        if migrated:
            self.db.execute(
                "UPDATE state SET body=? WHERE id=1", (self.vault.encode_state(json.loads(old[1])),)
            )
        self.db.execute("INSERT OR IGNORE INTO schema_migrations VALUES (1,?)", (time.time(),))
        self.db.commit()
        if migrated and local_database:
            self.db.execute("VACUUM")

    def initialized(self) -> bool:
        return self.db.execute("SELECT 1 FROM state WHERE id=1").fetchone() is not None

    def initialize(self, with_demo: bool = True) -> str | None:
        if self.initialized():
            return None
        token = secrets.token_urlsafe(32)
        servers = (
            [
                {
                    "id": "demo",
                    "transport": "stdio",
                    "command": "python",
                    "args": ["-m", "mvs.infrastructure.mcp.demo_server"],
                    "allowed_tools": ["add", "echo"],
                }
            ]
            if with_demo
            else []
        )
        state = {
            "servers": servers,
            "users": [
                {
                    "id": "admin",
                    "name": "管理员",
                    "tenant_id": "default",
                    "roles": ["admin"],
                    "servers": [s["id"] for s in servers],
                    "enabled": True,
                    "token_hash": token_hash(token),
                }
            ],
            "model": {},
            "secrets": {},
        }
        validate_state(state)
        self.db.execute("INSERT INTO state VALUES (1,1,?)", (self.vault.encode_state(state),))
        self.db.commit()
        path = self.root / "admin-token"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(token)
        return token

    def read(self) -> tuple[int, dict]:
        row = self.db.execute("SELECT revision,body FROM state WHERE id=1").fetchone()
        if row is None:
            raise ValueError("尚未初始化，请先运行 mvs init")
        return row[0], self.vault.decode_state(row[1])

    def save(self, expected: int, state: dict) -> int:
        validate_state(state)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO history SELECT revision,?,body FROM state WHERE id=1",
                (time.time(),),
            )
            cursor = self.db.execute(
                "UPDATE state SET revision=revision+1,body=? WHERE id=1 AND revision=?",
                (self.vault.encode_state(state), expected),
            )
            if cursor.rowcount != 1:
                raise ValueError("配置已被其他管理员更新，请刷新后重试")
        return expected + 1

    def history(self) -> list[dict]:
        return [
            {"revision": row[0], "created": row[1]}
            for row in self.db.execute(
                "SELECT revision,created FROM history ORDER BY revision DESC LIMIT 100"
            )
        ]

    def historical(self, revision: int) -> dict:
        row = self.db.execute("SELECT body FROM history WHERE revision=?", (revision,)).fetchone()
        if row is None:
            raise ValueError("历史版本不存在")
        return self.vault.decode_state(row[0])

    def public(self) -> dict:
        revision, state = self.read()
        result = copy.deepcopy(state)
        for user in result["users"]:
            user.pop("token_hash")
        result["secret_names"] = sorted(result.pop("secrets"))
        result["capabilities"] = {
            "approval": True,
            "model_protocols": ["responses", "chat_completions", "anthropic"],
            "shared_control": bool(os.environ.get("MVS_CONTROL_POSTGRES_DSN")),
            "shared_sessions": bool(os.environ.get("MVS_REDIS_URL")),
            "external_results": bool(os.environ.get("MVS_POSTGRES_DSN")),
            "isolated_validation": os.environ.get("MVS_ISOLATED_VALIDATION") == "1",
        }
        return {"revision": revision, **result}

    def authenticate(self, token: str) -> dict | None:
        if len(token) > 256:
            return None
        digest = token_hash(token)
        return next(
            (
                user
                for user in self.read()[1]["users"]
                if user["enabled"] and secrets.compare_digest(user["token_hash"], digest)
            ),
            None,
        )

    def event(self, event: dict) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO events(created,body) VALUES (?,?)",
                (time.time(), json.dumps(event, ensure_ascii=False)),
            )
            self.db.execute("DELETE FROM events WHERE id < (SELECT MAX(id)-2000 FROM events)")

    def events(self, limit: int = 100) -> list[dict]:
        return [
            {"id": row[0], "created": row[1], **json.loads(row[2])}
            for row in self.db.execute(
                "SELECT id,created,body FROM events ORDER BY id DESC LIMIT ?", (min(limit, 200),)
            )
        ]

    def close(self) -> None:
        self.db.close()
