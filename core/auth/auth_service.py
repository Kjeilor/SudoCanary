"""
Authentication service: credential verification, TOTP, user creation,
data notice acceptance, and failed attempt logging (DPPA S.23).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

import bcrypt

from core.auth.session import session_manager
from core.auth.totp import verify_code
from core.db.connection import get_connection
from core.models.user import User, SystemRole, RoomRole
from core.sdk.types import RoomId, UserId


class AuthError(Exception):
    pass


class AccountLocked(AuthError):
    pass


class AuthService:

    # ── Step 1: password verification ────────────────────────────────────────

    def verify_password(self, username: str, password: str) -> Optional[User]:
        """
        Verify username + password. Returns User on success, None on failure.
        Failed attempts are written to audit_log regardless of outcome.
        """
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? AND is_active = 1",
                (username,),
            ).fetchone()

            if row is None:
                self._log_failed_attempt(conn, username, "user_not_found")
                return None

            stored_hash = row["password_hash"].encode()
            if not bcrypt.checkpw(password.encode(), stored_hash):
                self._log_failed_attempt(
                    conn, username, "bad_password", user_id=row["user_id"]
                )
                return None

            role_rows = conn.execute(
                "SELECT room_id, role FROM room_roles WHERE user_id = ?",
                (row["user_id"],),
            ).fetchall()

        room_roles = {
            RoomId(r["room_id"]): RoomRole(r["role"]) for r in role_rows
        }

        return User(
            user_id=UserId(row["user_id"]),
            username=row["username"],
            display_name=row["display_name"],
            system_role=SystemRole(row["system_role"]) if row["system_role"] else None,
            room_roles=room_roles,
            totp_secret=row["totp_secret"],
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            last_login=(
                datetime.fromisoformat(row["last_login"])
                if row["last_login"] else None
            ),
            first_login_complete=bool(row["first_login_complete"]),
        )

    # ── Step 2 (first login only): data notice ────────────────────────────────

    def mark_data_notice_accepted(self, user_id: UserId) -> None:
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO data_notice_acceptances
                   (user_id, accepted_at, notice_version) VALUES (?, ?, ?)""",
                (user_id, now, "1.0"),
            )
            conn.execute(
                "UPDATE users SET first_login_complete = 1 WHERE user_id = ?",
                (user_id,),
            )

    # ── Step 3: TOTP verification ─────────────────────────────────────────────

    def verify_totp(self, session_id: str, code: str) -> bool:
        """
        Verify TOTP code for the user bound to this session.
        Always reads the secret fresh from DB — handles the just-enrolled case.
        """
        session = session_manager.get_session(session_id)
        if session is None:
            return False

        user = session_manager.get_user(session_id)
        if user is None:
            return False

        with get_connection() as conn:
            row = conn.execute(
                "SELECT totp_secret FROM users WHERE user_id = ?",
                (user.user_id,),
            ).fetchone()

        if not row or not row["totp_secret"]:
            return False

        if verify_code(row["totp_secret"], code):
            session_manager.mark_mfa_verified(session_id)
            self._update_last_login(user.user_id)
            return True

        with get_connection() as conn:
            self._log_failed_attempt(
                conn, user.username, "bad_totp", user_id=user.user_id
            )
        return False

    # ── User management ───────────────────────────────────────────────────────

    def create_user(
        self,
        username: str,
        display_name: str,
        password: str,
        system_role: Optional[SystemRole] = None,
    ) -> User:
        user_id = UserId(str(uuid.uuid4()))
        password_hash = bcrypt.hashpw(
            password.encode(), bcrypt.gensalt()
        ).decode()
        now = datetime.utcnow().isoformat()

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO users
                   (user_id, username, display_name, password_hash, system_role,
                    is_active, created_at, first_login_complete)
                   VALUES (?, ?, ?, ?, ?, 1, ?, 0)""",
                (
                    user_id, username, display_name, password_hash,
                    system_role.value if system_role else None, now,
                ),
            )

        return User(
            user_id=user_id,
            username=username,
            display_name=display_name,
            system_role=system_role,
            first_login_complete=False,
        )

    def enroll_totp(self, user_id: UserId, secret: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET totp_secret = ? WHERE user_id = ?",
                (secret, user_id),
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log_failed_attempt(
        self,
        conn,
        username: str,
        reason: str,
        user_id: Optional[str] = None,
    ) -> None:
        """DPPA S.23 — audit trail entry on every failed authentication."""
        conn.execute(
            """INSERT INTO audit_log
               (log_id, timestamp, user_id, username, action, resource, details, success)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                str(uuid.uuid4()),
                datetime.utcnow().isoformat(),
                user_id,
                username,
                "auth.login.failed",
                "auth",
                json.dumps({"reason": reason}),
            ),
        )

    def _update_last_login(self, user_id: UserId) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET last_login = ? WHERE user_id = ?",
                (datetime.utcnow().isoformat(), user_id),
            )


# Module-level singleton
auth_service = AuthService()