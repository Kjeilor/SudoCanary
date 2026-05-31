"""
core/db/retention.py

RetentionService — configurable data retention per room.

Default: 1095 days (3 years). Minimum: 365 days.
Purge requires explicit admin approval and is logged to audit trail.
Document and photo files are deleted from disk after DB row deletion.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from core.db.connection import get_connection
from core.sdk.types import RoomId, UserId

_MIN_DAYS = 365


class RetentionService:

    def get_retention_days(self, room_id: RoomId) -> int:
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT retention_days FROM rooms WHERE room_id=?",
                    (str(room_id),),
                ).fetchone()
            if row and row["retention_days"]:
                return row["retention_days"]
        except Exception:
            pass
        return 1095

    def set_retention_days(
        self,
        room_id: RoomId,
        days: int,
        set_by: UserId,
    ) -> None:
        if days < _MIN_DAYS:
            raise ValueError(f"Retention period cannot be less than {_MIN_DAYS} days.")

        current = self.get_retention_days(room_id)
        now = datetime.utcnow().isoformat()

        with get_connection() as conn:
            conn.execute(
                "UPDATE rooms SET retention_days=? WHERE room_id=?",
                (days, str(room_id)),
            )
            conn.execute(
                "INSERT INTO audit_log "
                "(log_id, timestamp, user_id, username, action, resource, details, success) "
                "VALUES (?,?,?,?,?,?,?,1)",
                (
                    str(uuid.uuid4()), now, str(set_by), "",
                    "retention.policy_updated", str(room_id),
                    json.dumps({"from_days": current, "to_days": days}),
                ),
            )

    def get_eligible_for_deletion(self, room_id: RoomId) -> dict:
        days    = self.get_retention_days(room_id)
        cutoff  = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rid     = str(room_id)

        with get_connection() as conn:
            sensor_count = conn.execute(
                "SELECT COUNT(*) FROM sensor_events "
                "WHERE room_id=? AND timestamp < ?",
                (rid, cutoff),
            ).fetchone()[0]

            audit_count = conn.execute(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE resource=? AND timestamp < ?",
                (rid, cutoff),
            ).fetchone()[0]

            doc_count = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE room_id=? AND created_at < ?",
                (rid, cutoff),
            ).fetchone()[0]

        return {
            "sensor_events": sensor_count,
            "audit_log":     audit_count,
            "documents":     doc_count,
            "cutoff_date":   cutoff[:10],
            "retention_days": days,
        }

    def purge_expired(
        self,
        room_id: RoomId,
        approved_by: UserId,
    ) -> dict:
        eligible = self.get_eligible_for_deletion(room_id)
        cutoff   = (datetime.utcnow() - timedelta(days=eligible["retention_days"])).isoformat()
        rid      = str(room_id)
        now      = datetime.utcnow().isoformat()
        deleted  = {"sensor_events": 0, "audit_log": 0, "documents": 0}

        with get_connection() as conn:
            # Delete document files from disk before removing DB rows
            doc_rows = conn.execute(
                "SELECT d.document_id, dv.file_path "
                "FROM documents d "
                "LEFT JOIN document_versions dv ON d.document_id = dv.document_id "
                "WHERE d.room_id=? AND d.created_at < ?",
                (rid, cutoff),
            ).fetchall()
            for row in doc_rows:
                if row["file_path"]:
                    try:
                        Path(row["file_path"]).unlink(missing_ok=True)
                    except Exception:
                        pass

            # Delete photo files
            photo_rows = conn.execute(
                "SELECT pc.photo_path FROM photo_checkins pc "
                "JOIN sensor_events se ON pc.event_id = se.event_id "
                "WHERE se.room_id=? AND se.timestamp < ?",
                (rid, cutoff),
            ).fetchall()
            for row in photo_rows:
                if row["photo_path"]:
                    try:
                        Path(row["photo_path"]).unlink(missing_ok=True)
                    except Exception:
                        pass

            deleted["documents"] = conn.execute(
                "DELETE FROM documents WHERE room_id=? AND created_at < ?",
                (rid, cutoff),
            ).rowcount

            deleted["sensor_events"] = conn.execute(
                "DELETE FROM sensor_events WHERE room_id=? AND timestamp < ?",
                (rid, cutoff),
            ).rowcount

            deleted["audit_log"] = conn.execute(
                "DELETE FROM audit_log WHERE resource=? AND timestamp < ?",
                (rid, cutoff),
            ).rowcount

            conn.execute(
                "INSERT INTO audit_log "
                "(log_id, timestamp, user_id, username, action, resource, details, success) "
                "VALUES (?,?,?,?,?,?,?,1)",
                (
                    str(uuid.uuid4()), now, str(approved_by), "",
                    "retention.purge_executed", rid,
                    json.dumps({**deleted, "cutoff": cutoff[:10]}),
                ),
            )

        return deleted


retention_service = RetentionService()