"""固定窗口限流：SQLite支持多进程，Redis支持跨实例共享。"""

import hashlib
import sqlite3
import time
from pathlib import Path


class RateLimiter:
    def __init__(self, path: Path, redis_url: str | None = None) -> None:
        self.redis = None
        if redis_url:
            import redis

            self.redis = redis.Redis.from_url(
                redis_url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5
            )
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS rate_limits "
            "(key TEXT,window INTEGER,count INTEGER,PRIMARY KEY(key,window))"
        )
        self.db.commit()

    def allow(self, tenant: str, principal: str, limit: int = 60) -> bool:
        window = int(time.time() // 60)
        key = hashlib.sha256(f"{tenant}\0{principal}".encode()).hexdigest()
        if self.redis:
            count = self.redis.eval(
                'local n=redis.call("INCR",KEYS[1]); '
                'if n==1 then redis.call("EXPIRE",KEYS[1],120) end; return n',
                1,
                f"mvs:rate:{key}:{window}",
            )
            return int(count) <= limit
        with self.db:
            self.db.execute(
                "INSERT INTO rate_limits VALUES (?,?,1) "
                "ON CONFLICT(key,window) DO UPDATE SET count=count+1",
                (key, window),
            )
            count = self.db.execute(
                "SELECT count FROM rate_limits WHERE key=? AND window=?", (key, window)
            ).fetchone()[0]
            self.db.execute("DELETE FROM rate_limits WHERE window<?", (window - 2,))
        return count <= limit

    def close(self) -> None:
        self.db.close()
        if self.redis:
            self.redis.close()
