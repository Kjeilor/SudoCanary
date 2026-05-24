"""
core/noticeboard_impl.py

NoticeBoardService: post, pin, list, and expire notices per room.

Expired notices (expires_at < now) are filtered from the active list
but remain in the database — consistent with the immutability principle.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from core.auth.rbac import can_post_notice, require_officer, require_room_access
from core.db.connection import get_connection
from core.models.user import User
from core.sdk.types import RoomId, UserId


class NoticeBoardService:

    def post_notice(
        self,
        actor: User,
        room_id: RoomId,
        title: str,
        body: str,
        expires_at: Optional[datetime] = None,
        pinned: bool = False,
    ) -> dict:
        if not can_post_notice(actor, room_id):
            from core.auth.rbac import PermissionDenied
            raise PermissionDenied("Posting notices requires Officer role or above.")

        notice_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO notices
                   (notice_id, room_id, author_id, title, body, pinned, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    notice_id, str(room_id), str(actor.user_id),
                    title, body, 1 if pinned else 0, now,
                    expires_at.isoformat() if expires_at else None,
                ),
            )

        return self._row_to_dict({
            "notice_id": notice_id, "room_id": str(room_id),
            "author_id": str(actor.user_id), "title": title, "body": body,
            "pinned": 1 if pinned else 0, "created_at": now,
            "expires_at": expires_at.isoformat() if expires_at else None,
        })

    def list_notices(
        self, room_id: RoomId, include_expired: bool = False
    ) -> List[dict]:
        """
        Returns notices for a room, pinned first, then newest first.
        Expired notices are excluded unless include_expired=True.
        """
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            if include_expired:
                rows = conn.execute(
                    "SELECT * FROM notices WHERE room_id = ? "
                    "ORDER BY pinned DESC, created_at DESC",
                    (str(room_id),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM notices WHERE room_id = ? "
                    "AND (expires_at IS NULL OR expires_at > ?) "
                    "ORDER BY pinned DESC, created_at DESC",
                    (str(room_id), now),
                ).fetchall()
        return [self._row_to_dict(dict(r)) for r in rows]

    def pin_notice(
        self, actor: User, room_id: RoomId, notice_id: str, pinned: bool
    ) -> None:
        require_officer(actor, room_id)
        with get_connection() as conn:
            conn.execute(
                "UPDATE notices SET pinned = ? WHERE notice_id = ? AND room_id = ?",
                (1 if pinned else 0, notice_id, str(room_id)),
            )

    def count_active(self, room_id: RoomId) -> int:
        """Count non-expired notices. Used to drive the bell badge."""
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM notices WHERE room_id = ? "
                "AND (expires_at IS NULL OR expires_at > ?)",
                (str(room_id), now),
            ).fetchone()
        return row[0] if row else 0

    def count_since(self, room_id: RoomId, since: datetime) -> int:
        """Count non-expired notices posted after `since`. Drives the bell badge."""
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM notices WHERE room_id = ? "
                "AND created_at > ? "
                "AND (expires_at IS NULL OR expires_at > ?)",
                (str(room_id), since.isoformat(), now),
            ).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _row_to_dict(r: dict) -> dict:
        return {
            "notice_id": r["notice_id"],
            "room_id":   r["room_id"],
            "author_id": r["author_id"],
            "title":     r["title"],
            "body":      r["body"],
            "pinned":    bool(r["pinned"]),
            "created_at": r["created_at"],
            "expires_at": r.get("expires_at"),
        }


noticeboard_service = NoticeBoardService()