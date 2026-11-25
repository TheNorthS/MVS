"""Redis会话状态和跨实例锁；同一会话的cwd/调用计数在锁内更新。"""

import asyncio
import json
import time
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from mvs.domain.errors import ShellError
from mvs.domain.models import SessionContext


class RedisLock:
    def __init__(self, client: Any, key: str) -> None:
        self.client = client
        self.key = key
        self.token = ""

    async def __aenter__(self) -> None:
        self.token = uuid4().hex
        while not await asyncio.to_thread(self.client.set, self.key, self.token, nx=True, ex=120):  # noqa: ASYNC110
            await asyncio.sleep(0.05)

    async def __aexit__(self, *exc: object) -> None:
        await asyncio.to_thread(
            self.client.eval,
            'if redis.call("GET",KEYS[1])==ARGV[1] then '
            'return redis.call("DEL",KEYS[1]) end; return 0',
            1,
            self.key,
            self.token,
        )


class LockMap:
    def __init__(self, client: Any) -> None:
        self.client = client

    def __getitem__(self, key: str) -> RedisLock:
        return RedisLock(self.client, "mvs:lock:" + key)


class RedisSessionStore:
    def __init__(self, url: str) -> None:
        import redis

        self.client = redis.Redis.from_url(
            url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5
        )
        self.locks = LockMap(self.client)

    def create(self, principal: str, tenant: str, ttl_s: int = 3600) -> SessionContext:
        session = SessionContext(
            uuid4().hex, principal, tenant, created_at=time.time(), expires_at=time.time() + ttl_s
        )
        self.persist(session)
        return session

    def persist(self, session: SessionContext) -> None:
        ttl = max(1, int(session.expires_at - time.time()))
        self.client.set("mvs:session:" + session.session_id, json.dumps(asdict(session)), ex=ttl)

    def get(self, session_id: str, principal: str, tenant: str) -> SessionContext:
        raw = self.client.get("mvs:session:" + session_id)
        if not raw:
            raise ShellError("NOT_FOUND", "会话不存在")
        session = SessionContext(**json.loads(raw))
        if (session.principal_id, session.tenant_id) != (
            principal,
            tenant,
        ) or session.expires_at <= time.time():
            raise ShellError("NOT_FOUND", "会话不存在")
        return session

    def delete(self, session_id: str, principal: str, tenant: str) -> None:
        self.get(session_id, principal, tenant)
        self.client.delete("mvs:session:" + session_id)

    def delete_expired(self) -> None:
        return None
