"""
core/sensors/qr_checkin.py

QRCheckInSensorImpl — implements PhotoCheckInPrimitive and QRTriggerPrimitive.

QR payload: base64-encoded JSON {"entity_id", "sensor_id", "room_id"}
Photo compression: Pillow, max 800px longest side, saved as JPEG
Storage: data/photos/{room_id}/{entity_id}/{entity_id}_{ts}_{event_id}.jpg

Entities are defined in the sensor's schema_json under the custom key
"x-entities": [{"id": "S1", "label": "Section 1"}, ...]

on_checkin() writes sensor_events + photo_checkins + audit_log atomically.
get_stale_entities() drives the Canary (Day 6).
"""
from __future__ import annotations

import base64
import io
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import qrcode
from PIL import Image

from core.db.connection import get_connection
from core.sdk.types import (
    ActionType, EventId, RoomId, SensorEvent, SensorId, UserId,
)

PHOTO_STORAGE_BASE = Path("data/photos")
MAX_PHOTO_PX = 800


def _compress_photo(source: str | Path | bytes) -> bytes:
    """
    Load image from path or bytes, convert to RGB, resize to MAX_PHOTO_PX
    on the longest side if needed, return JPEG bytes.
    """
    if isinstance(source, (str, Path)):
        img = Image.open(source)
    else:
        img = Image.open(io.BytesIO(source))

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > MAX_PHOTO_PX:
        if w >= h:
            new_w, new_h = MAX_PHOTO_PX, max(1, int(h * MAX_PHOTO_PX / w))
        else:
            new_w, new_h = max(1, int(w * MAX_PHOTO_PX / h)), MAX_PHOTO_PX
        img = img.resize((new_w, new_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


class QRCheckInSensorImpl:
    """
    Concrete implementation of PhotoCheckInPrimitive + QRTriggerPrimitive.
    Registered to a room just like a FormSensorImpl.
    """

    def __init__(
        self,
        sensor_id: SensorId,
        room_id: RoomId,
        label: str,
        schema: dict,
        stale_threshold_hours: int = 48,
        tool_id: Optional[str] = None,
    ) -> None:
        self.sensor_id = sensor_id
        self.room_id = room_id
        self.label = label
        self.schema = schema
        self.stale_threshold_hours = stale_threshold_hours
        self.tool_id = tool_id

    # ── Entity helpers ────────────────────────────────────────────────────────

    def get_entities(self) -> List[dict]:
        """Return list of {"id": ..., "label": ...} from schema x-entities."""
        return self.schema.get("x-entities", [])

    # ── QRTriggerPrimitive ────────────────────────────────────────────────────

    def generate_qr(self, entity_id: str) -> bytes:
        """Return PNG bytes of a QR code encoding a base64-JSON payload."""
        raw = json.dumps({
            "entity_id": entity_id,
            "sensor_id": str(self.sensor_id),
            "room_id":   str(self.room_id),
        })
        payload = base64.b64encode(raw.encode()).decode()
        img = qrcode.make(payload)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def decode_qr(self, qr_data: str) -> dict:
        """Decode a base64-JSON QR payload back to a dict."""
        raw = base64.b64decode(qr_data.encode()).decode()
        return json.loads(raw)

    def on_scan(self, qr_data: str, room_api: Any = None) -> SensorEvent:
        """Decode QR and return a placeholder event (full check-in via on_checkin)."""
        decoded = self.decode_qr(qr_data)
        return decoded  # caller opens check-in dialog with decoded["entity_id"]

    def get_schema(self) -> dict:
        return self.schema

    def validate(self, payload: dict) -> bool:
        return "entity_id" in payload and "photo_path" in payload

    def on_submit(self, event: SensorEvent, room_api: Any = None) -> None:
        pass  # callback not used for check-ins; logic is in on_checkin

    # ── PhotoCheckInPrimitive ─────────────────────────────────────────────────

    def on_checkin(
        self,
        entity_id: str,
        photo_source: str | Path | bytes,
        user_id: UserId,
        username: str = "",
        room_api: Any = None,
        gps_lat: Optional[float] = None,
        gps_lon: Optional[float] = None,
    ) -> SensorEvent:
        """
        Compress photo, save to disk, write sensor_events + photo_checkins +
        audit_log in a single transaction — atomic.
        """
        now = datetime.utcnow()
        event_id = EventId(str(uuid.uuid4()))

        # Compress
        jpeg_bytes = _compress_photo(photo_source)

        # Save to disk
        dest_dir = PHOTO_STORAGE_BASE / str(self.room_id) / str(entity_id)
        os.makedirs(dest_dir, exist_ok=True)
        ts_str = now.strftime("%Y%m%dT%H%M%S")
        filename = f"{entity_id}_{ts_str}_{event_id}.jpg"
        photo_path = dest_dir / filename
        photo_path.write_bytes(jpeg_bytes)

        payload: dict = {
            "entity_id":  entity_id,
            "photo_path": str(photo_path),
            "timestamp":  now.isoformat(),
        }
        if gps_lat is not None:
            payload["gps_lat"] = gps_lat
        if gps_lon is not None:
            payload["gps_lon"] = gps_lon

        provenance = SensorEvent.compute_provenance(payload, user_id, now)

        event = SensorEvent(
            event_id=event_id,
            room_id=self.room_id,
            sensor_id=self.sensor_id,
            user_id=user_id,
            timestamp=now,
            payload=payload,
            provenance=provenance,
        )

        with get_connection() as conn:
            conn.execute(
                "INSERT INTO sensor_events "
                "(event_id, room_id, sensor_id, user_id, timestamp, payload, provenance) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    str(event_id), str(self.room_id), str(self.sensor_id),
                    str(user_id), now.isoformat(), json.dumps(payload), provenance,
                ),
            )
            conn.execute(
                "INSERT INTO photo_checkins "
                "(event_id, entity_id, photo_path, gps_lat, gps_lon, timestamp) "
                "VALUES (?,?,?,?,?,?)",
                (str(event_id), entity_id, str(photo_path), gps_lat, gps_lon, now.isoformat()),
            )
            conn.execute(
                "INSERT INTO audit_log "
                "(log_id, timestamp, user_id, username, action, resource, details, success) "
                "VALUES (?,?,?,?,?,?,?,1)",
                (
                    str(uuid.uuid4()), now.isoformat(),
                    str(user_id), username,
                    ActionType.SENSOR_SUBMITTED.value,
                    str(self.room_id),
                    json.dumps({
                        "sensor_id":    str(self.sensor_id),
                        "sensor_label": self.label,
                        "entity_id":    entity_id,
                    }),
                ),
            )

        return event

    def get_last_checkin(
        self, entity_id: str, room_api: Any = None
    ) -> Optional[SensorEvent]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT se.* FROM sensor_events se "
                "JOIN photo_checkins pc ON se.event_id = pc.event_id "
                "WHERE se.room_id = ? AND se.sensor_id = ? AND pc.entity_id = ? "
                "ORDER BY se.timestamp DESC LIMIT 1",
                (str(self.room_id), str(self.sensor_id), entity_id),
            ).fetchone()
        if not row:
            return None
        import json as _json
        return SensorEvent(
            event_id=EventId(row["event_id"]),
            room_id=RoomId(row["room_id"]),
            sensor_id=SensorId(row["sensor_id"]),
            user_id=UserId(row["user_id"]),
            timestamp=datetime.fromisoformat(row["timestamp"]),
            payload=_json.loads(row["payload"]),
            provenance=row["provenance"],
        )

    def get_stale_entities(
        self,
        entity_ids: List[str],
        as_of: datetime,
        room_api: Any = None,
    ) -> List[str]:
        """Return entity_ids with no check-in within stale_threshold_hours."""
        stale = []
        for eid in entity_ids:
            last = self.get_last_checkin(eid, room_api)
            if last is None:
                stale.append(eid)
            else:
                hours = (as_of - last.timestamp).total_seconds() / 3600
                if hours > self.stale_threshold_hours:
                    stale.append(eid)
        return stale