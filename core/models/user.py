from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from core.sdk.types import RoomId, UserId


class SystemRole(str, Enum):
    ADMIN = "admin"


class RoomRole(str, Enum):
    OFFICER = "officer"
    VIEWER = "viewer"


@dataclass(frozen=True)
class User:
    user_id: UserId
    username: str
    display_name: str
    system_role: Optional[SystemRole]       # None = no system-wide privilege
    room_roles: dict[RoomId, RoomRole] = field(default_factory=dict)
    totp_secret: Optional[str] = None       # None until MFA is enrolled
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None
    first_login_complete: bool = False      # False until data notice accepted


@dataclass(frozen=True)
class Credentials:
    username: str
    password_hash: str                      # bcrypt
    salt: str


@dataclass
class Session:
    session_id: str
    user_id: UserId
    created_at: datetime
    last_active: datetime
    is_mfa_verified: bool = False

    def is_expired(self, timeout_minutes: int = 10) -> bool:
        delta = datetime.utcnow() - self.last_active
        return delta.total_seconds() > timeout_minutes * 60

    def touch(self) -> None:
        self.last_active = datetime.utcnow()