"""PostgreSQL原子配额+持久化结果，可选S3对象内容；每次读取仍校验租户/主体。"""

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from mvs.domain.errors import ShellError
from mvs.domain.models import ResultEnvelope


class PostgresResultStore:
    def __init__(
        self,
        dsn: str,
        quota: int = 64 * 1024 * 1024,
        bucket: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        import psycopg

        self.db = psycopg.connect(dsn)
        self.guard = threading.Lock()
        self.quota = quota
        self.bucket = bucket
        self.s3: Any = None
        if bucket:
            import boto3  # type: ignore[import-untyped]

            self.s3 = boto3.client("s3", endpoint_url=endpoint_url)
        with self.db.transaction():
            self.db.execute("""CREATE TABLE IF NOT EXISTS mvs_results(
                id TEXT PRIMARY KEY,tenant TEXT,owner TEXT,expires DOUBLE PRECISION,
                size BIGINT,hash TEXT,body BYTEA)""")

    async def put(
        self,
        result: ResultEnvelope,
        owner: tuple[str, str],
        ttl_s: int = 3600,
        assets: dict | None = None,
    ) -> str:
        raw = json.dumps(
            {"result": asdict(result), "assets": assets or {}}, ensure_ascii=False
        ).encode()
        if len(raw) > 4 * 1024 * 1024:
            raise ShellError("RESULT_TOO_LARGE", "结果过大")
        key = uuid4().hex

        def write() -> None:
            with self.guard, self.db.transaction():
                self.db.execute("SELECT pg_advisory_xact_lock(771995301)")
                row = self.db.execute("SELECT COALESCE(SUM(size),0) FROM mvs_results").fetchone()
                assert row is not None
                used = row[0]
                if used + len(raw) > self.quota:
                    raise ShellError("RESULT_TOO_LARGE", "存储总配额超限")
                if self.s3:
                    self.s3.put_object(Bucket=self.bucket, Key="mvs/" + key, Body=raw)
                self.db.execute(
                    "INSERT INTO mvs_results VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        key,
                        *owner,
                        time.time() + ttl_s,
                        len(raw),
                        hashlib.sha256(raw).hexdigest(),
                        None if self.s3 else raw,
                    ),
                )

        await asyncio.to_thread(write)
        return "/results/" + key

    def _load(self, key: str, owner: tuple[str, str]) -> dict:
        key = key.removeprefix("/results/")
        with self.guard, self.db.transaction():
            row = self.db.execute(
                "SELECT body,hash FROM mvs_results "
                "WHERE id=%s AND tenant=%s AND owner=%s AND expires>%s",
                (key, *owner, time.time()),
            ).fetchone()
        if row is None:
            raise ShellError("NOT_FOUND", "结果不存在")
        raw = (
            self.s3.get_object(Bucket=self.bucket, Key="mvs/" + key)["Body"].read()
            if self.s3
            else bytes(row[0])
        )
        if hashlib.sha256(raw).hexdigest() != row[1]:
            raise ShellError("INTERNAL_ERROR", "内容哈希不匹配")
        return json.loads(raw)

    async def get(self, result_id: str, principal: tuple[str, str]) -> ResultEnvelope:
        raw = (await asyncio.to_thread(self._load, result_id, principal))["result"]
        raw["text_blocks"] = tuple(raw["text_blocks"])
        raw["asset_refs"] = tuple(raw["asset_refs"])
        return ResultEnvelope(**raw)

    async def slice(
        self, result_id: str, principal: tuple[str, str], offset: int, limit: int
    ) -> object:
        if offset < 0 or not 0 <= limit <= 1000:
            raise ShellError("INVALID_ARGUMENT", "分页参数无效")
        result = await self.get(result_id, principal)
        value = (
            result.structured_data
            if result.structured_data is not None
            else "\n".join(result.text_blocks).splitlines()
        )
        if not isinstance(value, list):
            raise ShellError("INVALID_ARGUMENT", "分页需要数组或文本")
        return value[offset : offset + limit]

    async def get_asset(self, result_id: str, asset_id: str, principal: tuple[str, str]) -> dict:
        data = await asyncio.to_thread(self._load, result_id, principal)
        if asset_id not in data["assets"]:
            raise ShellError("NOT_FOUND", "附件不存在")
        return data["assets"][asset_id]

    async def delete_expired(self) -> int:
        def delete() -> int:
            with self.guard, self.db.transaction():
                rows = self.db.execute(
                    "DELETE FROM mvs_results WHERE expires<=%s RETURNING id", (time.time(),)
                ).fetchall()
                for row in rows:
                    if self.s3:
                        self.s3.delete_object(Bucket=self.bucket, Key="mvs/" + row[0])
                return len(rows)

        return await asyncio.to_thread(delete)

    def close(self) -> None:
        self.db.close()

    async def repair(self) -> dict:
        if not self.s3:
            return {"removed_orphans": 0, "missing": []}

        def inspect() -> dict:
            with self.guard, self.db.transaction():
                expected = {
                    row[0] for row in self.db.execute("SELECT id FROM mvs_results").fetchall()
                }
            seen = set()
            removed = 0
            for page in self.s3.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix="mvs/"
            ):
                for item in page.get("Contents", []):
                    key = item["Key"].removeprefix("mvs/")
                    seen.add(key)
                    if (
                        key not in expected
                        and item["LastModified"].timestamp() < time.time() - 3600
                    ):
                        self.s3.delete_object(Bucket=self.bucket, Key=item["Key"])
                        removed += 1
            return {"removed_orphans": removed, "missing": sorted(expected - seen)}

        return await asyncio.to_thread(inspect)
