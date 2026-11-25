import asyncio
import time
from uuid import uuid4

from mvs.domain.errors import ShellError
from mvs.domain.models import SessionContext


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionContext] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    def create(self, principal: str, tenant: str, ttl_s: int = 3600) -> SessionContext:
        self.delete_expired()
        if len(self.sessions) >= 10000:
            raise ShellError("LIMIT_EXCEEDED", "Session quota exceeded")
        session = SessionContext(
            uuid4().hex, principal, tenant, created_at=time.time(), expires_at=time.time() + ttl_s
        )
        self.sessions[session.session_id] = session
        self.locks[session.session_id] = asyncio.Lock()
        return session

    def get(self, session_id: str, principal: str, tenant: str) -> SessionContext:
        session = self.sessions.get(session_id)
        if (
            session is None
            or session.principal_id != principal
            or session.tenant_id != tenant
            or session.expires_at <= time.time()
        ):
            raise ShellError("NOT_FOUND", "Session not found")
        return session

    def delete(self, session_id: str, principal: str, tenant: str) -> None:
        self.get(session_id, principal, tenant)
        del self.sessions[session_id]
        del self.locks[session_id]

    def delete_expired(self) -> None:
        for key, session in list(self.sessions.items()):
            if session.expires_at <= time.time() and not self.locks[key].locked():
                del self.sessions[key]
                del self.locks[key]

    def persist(self, session: SessionContext) -> None:
        return None
