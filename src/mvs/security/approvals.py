"""审批绑定主体、租户、工具版本和参数摘要；批准仅允许一次原子消费。"""

import hashlib
import json
import time
from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

from mvs.domain.errors import ShellError
from mvs.domain.models import ToolDescriptor
from mvs.infrastructure.storage.control_db import control_database
from mvs.security.policy import Principal
from mvs.security.vault import Vault

approval_context: ContextVar[str | None] = ContextVar("approval_id", default=None)


def digest(arguments: dict) -> str:
    return hashlib.sha256(
        json.dumps(arguments, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class ApprovalStore:
    def __init__(self, root: Path) -> None:
        self.vault = Vault(root)
        self.db = control_database(root / "approvals.sqlite3")
        self.db.execute("""CREATE TABLE IF NOT EXISTS approvals(
            id TEXT PRIMARY KEY, tenant TEXT, owner TEXT, server TEXT, tool TEXT, revision TEXT,
            argument_hash TEXT, arguments TEXT, state TEXT,
            created REAL, expires REAL, reviewer TEXT)""")
        self.db.commit()

    def request(self, principal: Principal, tool: ToolDescriptor, arguments: dict) -> str:
        identity = uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identity,
                    principal.tenant_id,
                    principal.principal_id,
                    tool.server_id,
                    tool.name,
                    tool.revision,
                    digest(arguments),
                    json.dumps(self.vault.seal(arguments)),
                    "pending",
                    time.time(),
                    time.time() + 600,
                    None,
                ),
            )
        return identity

    def list(self) -> list[dict]:
        fields = [
            "id",
            "tenant",
            "owner",
            "server",
            "tool",
            "revision",
            "argument_hash",
            "state",
            "created",
            "expires",
            "reviewer",
        ]
        return [
            dict(zip(fields, row, strict=True))
            for row in self.db.execute(
                "SELECT id,tenant,owner,server,tool,revision,argument_hash,"
                "state,created,expires,reviewer "
                "FROM approvals ORDER BY created DESC LIMIT 200"
            )
        ]

    def details(self, identity: str) -> dict:
        row = self.db.execute("SELECT arguments FROM approvals WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise ValueError("审批不存在")
        return self.vault.open(json.loads(row[0]))

    def decide(self, identity: str, reviewer: str, approve: bool) -> None:
        with self.db:
            cursor = self.db.execute(
                "UPDATE approvals SET state=?,reviewer=? WHERE id=? AND state=? AND expires>?",
                ("approved" if approve else "rejected", reviewer, identity, "pending", time.time()),
            )
            if cursor.rowcount != 1:
                raise ValueError("审批不存在、已处理或已过期")

    def consume(
        self, identity: str, principal: Principal, tool: ToolDescriptor, arguments: dict
    ) -> None:
        with self.db:
            cursor = self.db.execute(
                """UPDATE approvals SET state='consumed' WHERE id=? AND tenant=? AND owner=?
                AND server=? AND tool=? AND revision=? AND argument_hash=?
                AND state='approved' AND expires>?""",
                (
                    identity,
                    principal.tenant_id,
                    principal.principal_id,
                    tool.server_id,
                    tool.name,
                    tool.revision,
                    digest(arguments),
                    time.time(),
                ),
            )
            if cursor.rowcount != 1:
                raise ShellError("POLICY_DENIED", "审批未批准、已消费、过期或调用内容已变化")

    def close(self) -> None:
        self.db.close()
