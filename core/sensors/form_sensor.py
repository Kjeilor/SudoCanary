"""
core/sensors/form_sensor.py

FormSensorImpl: implements FormSensorPrimitive Protocol against SQLite.

Constructor:
    FormSensorImpl(sensor_id, room_id, label, schema, on_submit_callback=None)

    on_submit_callback(event, room_api) is called after the event is
    persisted. RoadWorks passes its own callback on Day 8. Base is a no-op.

submit() writes sensor_events and audit_log in a single transaction — atomic.

SensorService: room-level helper for registering sensors and loading them
from the database. Used by the Sensors tab and the manual sensor builder.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import jsonschema

from core.db.connection import get_connection
from core.models.user import User
from core.sdk.types import (
    ActionType,
    EventId,
    RoomId,
    SensorEvent,
    SensorId,
    UserId,
)


class ValidationError(Exception):
    """Human-readable validation failure from FormSensorImpl.validate()."""


class FormSensorImpl:
    """Concrete implementation of FormSensorPrimitive."""

    def __init__(
        self,
        sensor_id: SensorId,
        room_id: RoomId,
        label: str,
        schema: Dict[str, Any],
        on_submit_callback: Optional[Callable] = None,
        tool_id: Optional[str] = None,
    ) -> None:
        self.sensor_id = sensor_id
        self.room_id = room_id
        self.label = label
        self.schema = schema
        self.tool_id = tool_id
        self._callback = on_submit_callback

    # ── Protocol methods ──────────────────────────────────────────────────────

    def get_schema(self) -> Dict[str, Any]:
        return self.schema

    def validate(self, payload: Dict[str, Any]) -> bool:
        try:
            jsonschema.validate(payload, self.schema)
            return True
        except jsonschema.ValidationError:
            return False

    def validate_with_message(self, payload: Dict[str, Any]) -> tuple[bool, str]:
        """Returns (True, "") or (False, human-readable message)."""
        try:
            jsonschema.validate(payload, self.schema)
            return True, ""
        except jsonschema.ValidationError as exc:
            field = exc.absolute_path[-1] if exc.absolute_path else "value"
            return False, f"{field}: {exc.message}"

    def on_submit(self, event: SensorEvent, room_api: Any = None) -> None:
        """Protocol hook — delegates to registered callback if present."""
        if self._callback:
            try:
                self._callback(event, room_api)
            except Exception:
                pass  # callback errors never roll back the submission

    # ── Submission ────────────────────────────────────────────────────────────

    def submit(self, actor: User, payload: Dict[str, Any]) -> SensorEvent:
        """
        Validate, persist, and audit a form submission.

        sensor_events insert + audit_log insert share one connection — atomic.
        Raises ValidationError if payload does not satisfy the schema.
        """
        ok, msg = self.validate_with_message(payload)
        if not ok:
            raise ValidationError(msg)

        now = datetime.utcnow()
        event_id = EventId(str(uuid.uuid4()))
        provenance = SensorEvent.compute_provenance(payload, actor.user_id, now)

        event = SensorEvent(
            event_id=event_id,
            room_id=self.room_id,
            sensor_id=self.sensor_id,
            user_id=actor.user_id,
            timestamp=now,
            payload=payload,
            provenance=provenance,
        )

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO sensor_events
                   (event_id, room_id, sensor_id, user_id, timestamp, payload, provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id, str(event.room_id), str(event.sensor_id),
                    str(event.user_id), now.isoformat(),
                    json.dumps(payload), provenance,
                ),
            )
            conn.execute(
                """INSERT INTO audit_log
                   (log_id, timestamp, user_id, username, action, resource, details, success)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    str(uuid.uuid4()),
                    now.isoformat(),
                    str(actor.user_id),
                    actor.username,
                    ActionType.SENSOR_SUBMITTED.value,
                    str(self.room_id),
                    json.dumps({"sensor_id": str(self.sensor_id), "sensor_label": self.label}),
                ),
            )

        self.on_submit(event)
        return event

    # ── Read ──────────────────────────────────────────────────────────────────

    def read_submissions(
        self,
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[SensorEvent]:
        clauses = ["room_id = ?", "sensor_id = ?"]
        params: list = [str(self.room_id), str(self.sensor_id)]
        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM sensor_events WHERE "
                + " AND ".join(clauses)
                + " ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()

        return [
            SensorEvent(
                event_id=EventId(r["event_id"]),
                room_id=RoomId(r["room_id"]),
                sensor_id=SensorId(r["sensor_id"]),
                user_id=UserId(r["user_id"]),
                timestamp=datetime.fromisoformat(r["timestamp"]),
                payload=json.loads(r["payload"]),
                provenance=r["provenance"],
            )
            for r in rows
        ]

    def last_submission_at(self) -> Optional[datetime]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT timestamp FROM sensor_events "
                "WHERE room_id = ? AND sensor_id = ? "
                "ORDER BY timestamp DESC LIMIT 1",
                (str(self.room_id), str(self.sensor_id)),
            ).fetchone()
        return datetime.fromisoformat(row["timestamp"]) if row else None


# ---------------------------------------------------------------------------
# SensorService — registration and loading
# ---------------------------------------------------------------------------

class SensorService:
    """Room-level sensor registry backed by the sensors table."""

    def register(
        self,
        sensor_id: str,
        room_id: str,
        label: str,
        schema: Dict[str, Any],
        tool_id: Optional[str] = None,
        on_submit_callback: Optional[Callable] = None,
    ) -> FormSensorImpl:
        """Write a sensor registration and return the loaded instance."""
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sensors
                   (sensor_id, room_id, tool_id, label, schema_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (sensor_id, room_id, tool_id, label, json.dumps(schema), now),
            )
        return FormSensorImpl(
            SensorId(sensor_id), RoomId(room_id), label, schema,
            on_submit_callback, tool_id,
        )

    def load_for_room(
        self,
        room_id: str,
        callbacks: Optional[Dict[str, Callable]] = None,
    ) -> List[FormSensorImpl]:
        """Load all sensors registered to a room from the database."""
        callbacks = callbacks or {}
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM sensors WHERE room_id = ? ORDER BY created_at",
                (room_id,),
            ).fetchall()
        return [
            FormSensorImpl(
                SensorId(r["sensor_id"]),
                RoomId(r["room_id"]),
                r["label"],
                json.loads(r["schema_json"]),
                callbacks.get(r["sensor_id"]),
                r["tool_id"],
            )
            for r in rows
        ]

    def delete(self, sensor_id: str, room_id: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM sensors WHERE sensor_id = ? AND room_id = ?",
                (sensor_id, room_id),
            )


sensor_service = SensorService()