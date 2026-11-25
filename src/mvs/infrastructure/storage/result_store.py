import hashlib
import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from mvs.domain.errors import ShellError
from mvs.domain.models import ResultEnvelope
from mvs.domain.telemetry import Telemetry


class ResultStore:
    """SQLite metadata and private object files. No caller-controlled filesystem paths."""

    def __init__(
        self, root: Path, quota: int = 64 * 1024 * 1024, telemetry: Telemetry | None = None
    ) -> None:
        self.telemetry = telemetry or Telemetry()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.objects = root / "objects"
        self.objects.mkdir(exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(root / "results.sqlite")
        self.db.execute("""CREATE TABLE IF NOT EXISTS results (
            id TEXT PRIMARY KEY, tenant TEXT, owner TEXT, created REAL, expires REAL,
            size INTEGER, sha256 TEXT, server TEXT, tool TEXT, mime TEXT)""")
        self.quota = quota

    async def put(
        self,
        result: ResultEnvelope,
        owner: tuple[str, str],
        ttl_s: int = 3600,
        assets: dict | None = None,
    ) -> str:
        await self.delete_expired()
        raw = json.dumps(
            {"result": asdict(result), "assets": assets or {}}, ensure_ascii=False, allow_nan=False
        ).encode()
        if len(raw) > 4 * 1024 * 1024:
            raise ShellError("RESULT_TOO_LARGE", "Result exceeds 4 MiB")
        key = uuid4().hex
        path = self.objects / key
        try:
            self.db.execute("BEGIN IMMEDIATE")
            used = self.db.execute("SELECT COALESCE(SUM(size),0) FROM results").fetchone()[0]
            if used + len(raw) > self.quota:
                raise ShellError("RESULT_TOO_LARGE", "Result storage quota exceeded")
            path.write_bytes(raw)
            self.db.execute(
                "INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    *owner,
                    time.time(),
                    time.time() + ttl_s,
                    len(raw),
                    hashlib.sha256(raw).hexdigest(),
                    result.server_id,
                    result.tool_name,
                    "application/json",
                ),
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            path.unlink(missing_ok=True)
            raise
        self.telemetry.result_stored(result.server_id, len(raw))
        return "/results/" + key

    def _load(self, result_id: str, principal: tuple[str, str]) -> dict:
        key = result_id.removeprefix("/results/")
        row = self.db.execute(
            "SELECT sha256 FROM results WHERE id=? AND tenant=? AND owner=? AND expires>?",
            (key, *principal, time.time()),
        ).fetchone()
        if row is None:
            existing = self.db.execute(
                "SELECT tenant, owner FROM results WHERE id=?", (key,)
            ).fetchone()
            if existing and tuple(existing) != principal:
                self.telemetry.policy_denied("", "result_not_owned")
            raise ShellError("NOT_FOUND", "Result not found")
        raw = (self.objects / key).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row[0]:
            raise ShellError("INTERNAL_ERROR", "Stored result integrity check failed")
        return json.loads(raw)

    async def get(self, result_id: str, principal: tuple[str, str]) -> ResultEnvelope:
        raw = self._load(result_id, principal)["result"]
        for key in ("text_blocks", "asset_refs"):
            raw[key] = tuple(raw[key])
        return ResultEnvelope(**raw)

    async def slice(
        self, result_id: str, principal: tuple[str, str], offset: int, limit: int
    ) -> object:
        if offset < 0 or not 0 <= limit <= 1000:
            raise ShellError("INVALID_ARGUMENT", "Page limit must be 0..1000; offset nonnegative")
        result = await self.get(result_id, principal)
        data = result.structured_data
        if data is None:
            data = "\n".join(result.text_blocks).splitlines()
        if not isinstance(data, list):
            raise ShellError("INVALID_ARGUMENT", "Pagination requires an array or text")
        return data[offset : offset + limit]

    async def get_asset(self, result_id: str, asset_id: str, principal: tuple[str, str]) -> dict:
        assets = self._load(result_id, principal)["assets"]
        if asset_id not in assets:
            raise ShellError("NOT_FOUND", "Asset not found")
        return assets[asset_id]

    async def delete_expired(self) -> int:
        keys = self.db.execute("SELECT id FROM results WHERE expires<=?", (time.time(),)).fetchall()
        for (key,) in keys:
            (self.objects / key).unlink(missing_ok=True)
            self.db.execute("DELETE FROM results WHERE id=?", (key,))
        self.db.commit()
        return len(keys)

    def close(self) -> None:
        self.db.close()

    def repair(self) -> dict:
        """离线维护：移除无元数据对象，报告丢失/损坏内容。"""
        referenced = {row[0]: row[1] for row in self.db.execute("SELECT id,sha256 FROM results")}
        orphans = 0
        missing = []
        corrupt = []
        for path in self.objects.iterdir():
            if path.is_file() and path.name not in referenced:
                path.unlink()
                orphans += 1
        for key, digest in referenced.items():
            path = self.objects / key
            if not path.exists():
                missing.append(key)
            elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                corrupt.append(key)
        return {"removed_orphans": orphans, "missing": missing, "corrupt": corrupt}
