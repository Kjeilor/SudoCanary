"""
SQLite-backed implementation of the RoomAPI Protocol.

Every mutating method:
  1. Enforces RBAC via core.auth.rbac
  2. Writes to the database
  3. Appends to audit_log in the same transaction

Note: method signatures here are intentional — adjust to match the exact
Protocol defined in core/sdk/room.py once you reconcile Day 1 interfaces.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional, Sequence

from core.auth.rbac import (
    require_admin,
    require_officer,
    require_room_access,
    PermissionDenied,
)
from core.db.connection import get_connection
from core.models.user import User, RoomRole
from core.sdk.types import RoomId, UserId


class RoomAPIImpl:
    """Implements core/sdk/room.py :: RoomAPI Protocol."""

    def __init__(self, actor: User) -> None:
        self._actor = actor

    # ── Room lifecycle ────────────────────────────────────────────────────────

    def create_room(self, name: str, description: str = "") -> RoomId:
        require_admin(self._actor)
        room_id = RoomId(str(uuid.uuid4()))
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO rooms (room_id, name, description, created_at, created_by)"
                " VALUES (?, ?, ?, ?, ?)",
                (room_id, name, description, now, self._actor.user_id),
            )
            self._audit(conn, "room.create", room_id, {"name": name})
        return room_id

    def list_rooms(self) -> Sequence[dict]:
        with get_connection() as conn:
            if self._actor.system_role == "admin":
                rows = conn.execute(
                    "SELECT * FROM rooms ORDER BY name"
                ).fetchall()
            else:
                accessible = list(self._actor.room_roles.keys())
                if not accessible:
                    return []
                placeholders = ",".join("?" * len(accessible))
                rows = conn.execute(
                    f"SELECT * FROM rooms WHERE room_id IN ({placeholders})"
                    f" ORDER BY name",
                    accessible,
                ).fetchall()
        return [dict(r) for r in rows]

    def get_room(self, room_id: RoomId) -> Optional[dict]:
        require_room_access(self._actor, room_id)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM rooms WHERE room_id = ?", (room_id,)
            ).fetchone()
        return dict(row) if row else None

    # ── Member management ─────────────────────────────────────────────────────

    def add_member(
        self, room_id: RoomId, user_id: UserId, role: RoomRole
    ) -> None:
        require_officer(self._actor, room_id)
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO room_roles (user_id, room_id, role)"
                " VALUES (?, ?, ?)",
                (user_id, room_id, role.value),
            )
            self._audit(
                conn, "room.member.add", room_id,
                {"user_id": user_id, "role": role.value},
            )

    def remove_member(self, room_id: RoomId, user_id: UserId) -> None:
        require_officer(self._actor, room_id)
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM room_roles WHERE user_id = ? AND room_id = ?",
                (user_id, room_id),
            )
            self._audit(
                conn, "room.member.remove", room_id, {"user_id": user_id}
            )

    def list_members(self, room_id: RoomId) -> Sequence[dict]:
        require_room_access(self._actor, room_id)
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT u.user_id, u.username, u.display_name, rr.role
                   FROM room_roles rr
                   JOIN users u USING(user_id)
                   WHERE rr.room_id = ?
                   ORDER BY u.display_name""",
                (room_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Audit helper ──────────────────────────────────────────────────────────

    def _audit(
        self,
        conn,
        action: str,
        resource: str,
        details: dict,
        success: bool = True,
    ) -> None:
        conn.execute(
            """INSERT INTO audit_log
               (log_id, timestamp, user_id, username, action, resource, details, success)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                datetime.utcnow().isoformat(),
                self._actor.user_id,
                self._actor.username,
                action,
                resource,
                json.dumps(details),
                1 if success else 0,
            ),
        )