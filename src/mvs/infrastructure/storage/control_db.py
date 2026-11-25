"""控制面数据库兼容层；PostgreSQL模式多实例共享版本、审批、OAuth与审计。"""

import os
import sqlite3
from pathlib import Path
from typing import Any


class PostgresControl:
    def __init__(self, dsn: str) -> None:
        import psycopg

        self.connection = psycopg.connect(dsn, autocommit=True)
        self.transaction: Any = None

    def execute(self, sql: str, args: tuple = ()) -> Any:
        statement = sql.replace("?", "%s")
        statement = statement.replace(
            "id INTEGER PRIMARY KEY, created REAL",
            "id BIGSERIAL PRIMARY KEY, created DOUBLE PRECISION",
        )
        statement = statement.replace(" REAL", " DOUBLE PRECISION")
        if "INSERT OR IGNORE INTO" in statement:
            statement = (
                statement.replace("INSERT OR IGNORE INTO", "INSERT INTO")
                + " ON CONFLICT DO NOTHING"
            )
        if "INSERT OR REPLACE INTO oauth_tokens" in statement:
            statement = (
                statement.replace("INSERT OR REPLACE INTO", "INSERT INTO")
                + " ON CONFLICT(owner,provider) DO UPDATE SET body=excluded.body"
            )
        return self.connection.execute(statement, args)

    def __enter__(self) -> "PostgresControl":
        self.transaction = self.connection.transaction()
        self.transaction.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.transaction.__exit__(*exc)

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self.connection.close()


def control_database(path: Path) -> Any:
    dsn = os.environ.get("MVS_CONTROL_POSTGRES_DSN")
    if dsn:
        if not os.environ.get("MVS_VAULT_KEY"):
            raise ValueError("共享控制数据库要求所有实例配置相同MVS_VAULT_KEY")
        return PostgresControl(dsn)
    return sqlite3.connect(path, timeout=10, check_same_thread=False)
