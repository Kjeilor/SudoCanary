"""
core/export/data_export.py

DataExporter — exports room data to CSV for external analysis.

CSV files written to data/exports/{room_id}/ with timestamp in filename.
All exports logged to audit trail.
"""
from __future__ import annotations

import csv
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.db.connection import get_connection
from core.sdk.types import RoomId, SensorId, UserId

_EXPORT_BASE = Path("data/exports")


class DataExporter:

    def export_sensor_events(
        self,
        room_id: RoomId,
        sensor_id: Optional[SensorId],
        since: Optional[datetime],
        until: Optional[datetime],
        exported_by: UserId,
    ) -> str:
        rid   = str(room_id)
        now   = datetime.utcnow()
        clauses = ["room_id = ?"]
        params  = [rid]

        if sensor_id:
            clauses.append("sensor_id = ?")
            params.append(str(sensor_id))
        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        if until:
            clauses.append("timestamp <= ?")
            params.append(until.isoformat())

        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM sensor_events WHERE {' AND '.join(clauses)} "
                "ORDER BY timestamp DESC",
                params,
            ).fetchall()

        path = self._write_csv(
            room_id, "sensor_events",
            ["event_id", "sensor_id", "room_id", "user_id", "timestamp", "payload"],
            [dict(r) for r in rows],
        )
        self._log(room_id, exported_by, "sensor_events", len(rows), path)
        return path

    def export_tasks(self, room_id: RoomId, exported_by: UserId) -> str:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT t.*, u.display_name as assignee_name "
                "FROM tasks t LEFT JOIN users u ON t.assigned_to = u.user_id "
                "WHERE t.room_id=? ORDER BY t.created_at DESC",
                (str(room_id),),
            ).fetchall()

        path = self._write_csv(
            room_id, "tasks",
            ["task_id", "title", "status", "assignee_name", "created_at", "due_at", "tags"],
            [dict(r) for r in rows],
        )
        self._log(room_id, exported_by, "tasks", len(rows), path)
        return path

    def export_audit_trail(
        self,
        room_id: RoomId,
        exported_by: UserId,
        since: Optional[datetime] = None,
    ) -> str:
        clauses = ["resource = ?"]
        params  = [str(room_id)]
        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())

        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_log WHERE {' AND '.join(clauses)} "
                "ORDER BY timestamp DESC",
                params,
            ).fetchall()

        path = self._write_csv(
            room_id, "audit_trail",
            ["log_id", "timestamp", "username", "action", "resource", "details", "success"],
            [dict(r) for r in rows],
        )
        self._log(room_id, exported_by, "audit_trail", len(rows), path)
        return path

    # ── Internal ─────────────────────────────────────────────────────────────

    def _write_csv(
        self,
        room_id: RoomId,
        name: str,
        columns: list,
        rows: list,
    ) -> str:
        out_dir = _EXPORT_BASE / str(room_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"{name}_{ts}.csv"

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        return str(path)

    def _log(
        self,
        room_id: RoomId,
        user_id: UserId,
        export_type: str,
        row_count: int,
        file_path: str,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO audit_log "
                "(log_id, timestamp, user_id, username, action, resource, details, success) "
                "VALUES (?,?,?,?,?,?,?,1)",
                (
                    str(uuid.uuid4()), now, str(user_id), "",
                    "data.exported", str(room_id),
                    json.dumps({"type": export_type, "rows": row_count,
                                "file": Path(file_path).name}),
                ),
            )


data_exporter = DataExporter()