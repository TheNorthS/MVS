"""读请求并行，配置写者优先，切换仅等待已在途请求。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class RuntimeGate:
    def __init__(self) -> None:
        self.condition = asyncio.Condition()
        self.readers = 0
        self.writing = False
        self.waiting = 0

    @asynccontextmanager
    async def read(self) -> AsyncIterator[None]:
        async with self.condition:
            await self.condition.wait_for(lambda: not self.writing and not self.waiting)
            self.readers += 1
        try:
            yield
        finally:
            async with self.condition:
                self.readers -= 1
                self.condition.notify_all()

    async def __aenter__(self) -> None:
        async with self.condition:
            self.waiting += 1
            try:
                await self.condition.wait_for(lambda: not self.writing and not self.readers)
                self.writing = True
            finally:
                self.waiting -= 1
                self.condition.notify_all()

    async def __aexit__(self, *args: object) -> None:
        async with self.condition:
            self.writing = False
            self.condition.notify_all()
