"""
In-memory session store.
Sessions intentionally do not persist across restarts — offline-first,
no session tokens written to disk.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, Optional

from core.models.user import Session, User
from core.sdk.types import UserId

SESSION_TIMEOUT_MINUTES = 10


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}
        self._user_cache: Dict[UserId, User] = {}

    def create_session(self, user: User) -> Session:
        now = datetime.utcnow()
        session = Session(
            session_id=str(uuid.uuid4()),
            user_id=user.user_id,
            created_at=now,
            last_active=now,
            is_mfa_verified=False,
        )
        self._sessions[session.session_id] = session
        self._user_cache[user.user_id] = user
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired(SESSION_TIMEOUT_MINUTES):
            self.invalidate(session_id)
            return None
        return session

    def touch(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.touch()

    def mark_mfa_verified(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session:
            session.is_mfa_verified = True

    def invalidate(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            self._user_cache.pop(session.user_id, None)

    def get_user(self, session_id: str) -> Optional[User]:
        session = self.get_session(session_id)
        if session is None:
            return None
        return self._user_cache.get(session.user_id)

    def is_fully_authenticated(self, session_id: str) -> bool:
        session = self.get_session(session_id)
        return session is not None and session.is_mfa_verified


# Module-level singleton
session_manager = SessionManager()