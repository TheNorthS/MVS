import asyncio
import json
import os
from dataclasses import asdict

import pytest

from mvs.domain.errors import ShellError
from mvs.domain.models import ResultEnvelope


@pytest.mark.skipif(not os.environ.get("MVS_TEST_REDIS_URL"), reason="需要真实Redis测试实例")
async def test_redis_shared_sessions_and_limits(tmp_path):
    from mvs.infrastructure.storage.rate_limit import RateLimiter
    from mvs.infrastructure.storage.redis_sessions import RedisSessionStore

    url = os.environ["MVS_TEST_REDIS_URL"]
    first, second = RedisSessionStore(url), RedisSessionStore(url)
    session = first.create("storage-test", "test")
    async with first.locks[session.session_id]:
        session.cwd = "/os"
        first.persist(session)
    assert second.get(session.session_id, "storage-test", "test").cwd == "/os"
    with pytest.raises(ShellError):
        second.get(session.session_id, "wrong", "test")
    limiter = RateLimiter(tmp_path / "rate.db", url)
    for _ in range(3):
        assert limiter.allow("test", session.session_id, 3)
    assert not limiter.allow("test", session.session_id, 3)
    first.delete(session.session_id, "storage-test", "test")
    limiter.close()


@pytest.mark.skipif(
    not os.environ.get("MVS_TEST_POSTGRES_DSN"), reason="需要真实PostgreSQL测试实例"
)
async def test_postgres_owner_and_pagination(postgres_dsn):
    from mvs.infrastructure.storage.postgres_results import PostgresResultStore

    store = PostgresResultStore(postgres_dsn)
    try:
        ref = await store.put(
            ResultEnvelope("req", "demo", "list", True, [1, 2, 3]), ("test", "owner"), ttl_s=10
        )
        assert await store.slice(ref, ("test", "owner"), 1, 2) == [2, 3]
        with pytest.raises(ShellError):
            await store.get(ref, ("test", "other"))
    finally:
        store.close()


async def test_postgres_concurrent_quota_is_atomic(postgres_dsn):
    from mvs.infrastructure.storage.postgres_results import PostgresResultStore

    envelope = ResultEnvelope("req", "demo", "value", True, {"value": "x" * 256})
    size = len(json.dumps({"result": asdict(envelope), "assets": {}}, ensure_ascii=False).encode())
    stores = [PostgresResultStore(postgres_dsn, quota=size * 3) for _ in range(10)]
    try:
        results = await asyncio.gather(
            *(s.put(envelope, ("quota", "owner")) for s in stores), return_exceptions=True
        )
        assert sum(isinstance(r, str) for r in results) == 3
        assert all(
            isinstance(r, str) or isinstance(r, ShellError) and r.code == "RESULT_TOO_LARGE"
            for r in results
        )
        with stores[0].db.transaction():
            count, total = (
                stores[0].db.execute("SELECT COUNT(*),SUM(size) FROM mvs_results").fetchone()
            )
        assert count == 3 and total == size * 3
    finally:
        for store in stores:
            store.close()


async def test_real_s3_assets_ttl_integrity_and_repair(postgres_dsn, s3_bucket, monkeypatch):
    from datetime import UTC, datetime

    from mvs.infrastructure.storage.postgres_results import PostgresResultStore

    client, bucket, endpoint = s3_bucket
    store = PostgresResultStore(postgres_dsn, bucket=bucket, endpoint_url=endpoint)
    result = ResultEnvelope("req", "demo", "image", True, {"value": 1}, asset_refs=("asset1",))
    asset = {"type": "image", "mime_type": "image/png", "data": "opaque-test-payload"}
    try:
        ref = await store.put(result, ("tenant", "owner"), assets={"asset1": asset})
        assert await store.get_asset(ref, "asset1", ("tenant", "owner")) == asset
        for owner in [("tenant", "other"), ("other", "owner")]:
            with pytest.raises(ShellError):
                await store.get(ref, owner)
        key = "mvs/" + ref.rsplit("/", 1)[-1]
        with store.db.transaction():
            assert store.db.execute("SELECT body FROM mvs_results").fetchone()[0] is None
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        assert b"opaque-test-payload" in body
        client.put_object(Bucket=bucket, Key=key, Body=b"tampered")
        with pytest.raises(ShellError) as error:
            await store.get(ref, ("tenant", "owner"))
        assert error.value.code == "INTERNAL_ERROR"
        client.put_object(Bucket=bucket, Key=key, Body=body)
        client.put_object(Bucket=bucket, Key="mvs/orphan", Body=b"orphan")
        client.put_object(Bucket=bucket, Key="unrelated/keep", Body=b"keep")
        real_time = datetime.now(UTC).timestamp()
        with monkeypatch.context() as clock:
            clock.setattr(
                "mvs.infrastructure.storage.postgres_results.time.time", lambda: real_time + 7200
            )
            repair = await store.repair()
            assert repair == {"removed_orphans": 1, "missing": []}
        assert client.get_object(Bucket=bucket, Key="unrelated/keep")["Body"].read() == b"keep"
        client.delete_object(Bucket=bucket, Key=key)
        assert (await store.repair())["missing"] == [ref.rsplit("/", 1)[-1]]
        expired = await store.put(result, ("tenant", "owner"), ttl_s=-1)
        assert await store.delete_expired() == 1
        with pytest.raises(ShellError):
            await store.get(expired, ("tenant", "owner"))
        keys = {item["Key"] for item in client.list_objects_v2(Bucket=bucket).get("Contents", [])}
        assert "mvs/" + expired.rsplit("/", 1)[-1] not in keys
    finally:
        store.close()
