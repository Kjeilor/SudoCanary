"""
tools/roadworks/sensors.py

Four RoadWorks sensors — schemas + on_submit callbacks.
"""
from __future__ import annotations
import json, uuid
from datetime import datetime
from typing import Any

# ── Schemas ───────────────────────────────────────────────────────────────────

KM_PROGRESS_SCHEMA = {
    "x-sensor-type": "form",
    "type": "object", "title": "Daily KM Progress",
    "properties": {
        "section_id": {"type": "string", "title": "Section",
                       "enum": ["S1","S2","S3","S4","S5","S6"]},
        "km_paved":   {"type": "number", "title": "KM Paved Today",
                       "minimum": 0, "maximum": 2.0},
        "date":       {"type": "string", "title": "Date", "format": "date"},
        "notes":      {"type": "string", "title": "Notes"},
    },
    "required": ["section_id", "km_paved", "date"],
}

MATERIALS_SCHEMA = {
    "x-sensor-type": "form",
    "type": "object", "title": "Materials Log",
    "properties": {
        "section_id":         {"type": "string", "title": "Section",
                               "enum": ["S1","S2","S3","S4","S5","S6"]},
        "material":           {"type": "string", "title": "Material",
                               "enum": ["aggregate","bitumen","concrete","steel","other"]},
        "quantity_acquired":  {"type": "number", "title": "Qty Acquired", "minimum": 0},
        "quantity_consumed":  {"type": "number", "title": "Qty Consumed", "minimum": 0},
        "unit":               {"type": "string", "title": "Unit",
                               "enum": ["tonnes","m3","litres","units"]},
        "date":               {"type": "string", "title": "Date", "format": "date"},
    },
    "required": ["section_id","material","quantity_acquired","quantity_consumed","unit","date"],
}

QA_SIGNOFF_SCHEMA = {
    "x-sensor-type": "form",
    "type": "object", "title": "QA Section Sign-off",
    "properties": {
        "section_id":          {"type": "string", "title": "Section",
                                "enum": ["S1","S2","S3","S4","S5","S6"]},
        "approved":            {"type": "boolean", "title": "Approved"},
        "inspector_name":      {"type": "string",  "title": "Inspector Name"},
        "inspection_date":     {"type": "string",  "title": "Inspection Date", "format": "date"},
        "notes":               {"type": "string",  "title": "Notes"},
        "supersession_reason": {"type": "string",
                                "title": "Supersession Reason (required if re-approving)"},
    },
    "required": ["section_id","approved","inspector_name","inspection_date"],
}

PHOTO_CHECKIN_SCHEMA = {
    "x-sensor-type": "qr_checkin",
    "x-entities": [
        {"id": "S1", "label": "Section 1"},
        {"id": "S2", "label": "Section 2"},
        {"id": "S3", "label": "Section 3"},
        {"id": "S4", "label": "Section 4"},
        {"id": "S5", "label": "Section 5"},
        {"id": "S6", "label": "Section 6"},
    ],
    "x-stale-hours": 48,
}

# ── Callbacks ─────────────────────────────────────────────────────────────────

def km_progress_callback(event: Any, room_api: Any) -> None:
    from core.db.connection import get_connection
    payload = event.payload
    room_id = str(event.room_id)
    section_id = payload.get("section_id")
    km_paved   = float(payload.get("km_paved", 0))
    date       = payload.get("date", "")
    with get_connection() as conn:
        prev = conn.execute(
            "SELECT COALESCE(MAX(cumulative_km),0) FROM roadworks_km_progress "
            "WHERE section_id=? AND room_id=?", (section_id, room_id)
        ).fetchone()[0]
        cumulative = prev + km_paved
        conn.execute(
            "INSERT OR IGNORE INTO roadworks_km_progress "
            "(event_id, section_id, room_id, km_paved, date, cumulative_km) VALUES (?,?,?,?,?,?)",
            (str(event.event_id), section_id, room_id, km_paved, date, cumulative),
        )
        row = conn.execute(
            "SELECT length_km, status FROM roadworks_sections WHERE section_id=? AND room_id=?",
            (section_id, room_id)
        ).fetchone()
        if row and row["status"] not in ("qa_approved",):
            new_status = "complete" if cumulative >= row["length_km"] else "in_progress"
            conn.execute(
                "UPDATE roadworks_sections SET status=?, updated_at=? WHERE section_id=? AND room_id=?",
                (new_status, datetime.utcnow().isoformat(), section_id, room_id),
            )
    _trigger(event.room_id)


def materials_callback(event: Any, room_api: Any) -> None:
    from core.db.connection import get_connection
    p = event.payload
    room_id    = str(event.room_id)
    acquired   = float(p.get("quantity_acquired", 0))
    consumed   = float(p.get("quantity_consumed", 0))
    divergence = round((consumed - acquired) / acquired * 100, 2) if acquired > 0 else None
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO roadworks_materials "
            "(event_id, section_id, room_id, material, quantity_acquired, "
            " quantity_consumed, unit, date, divergence_pct) VALUES (?,?,?,?,?,?,?,?,?)",
            (str(event.event_id), p.get("section_id"), room_id, p.get("material"),
             acquired, consumed, p.get("unit"), p.get("date",""), divergence),
        )
    _trigger(event.room_id)


def qa_signoff_callback(event: Any, room_api: Any) -> None:
    from core.db.connection import get_connection
    p = event.payload
    room_id    = str(event.room_id)
    section_id = p.get("section_id")
    approved   = p.get("approved", False)
    if not approved:
        _trigger(event.room_id); return
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM roadworks_sections WHERE section_id=? AND room_id=?",
            (section_id, room_id)
        ).fetchone()
        if row and row["status"] == "qa_approved":
            reason = p.get("supersession_reason", "").strip()
            if not reason:
                conn.execute(
                    "INSERT INTO audit_log (log_id,timestamp,user_id,username,action,resource,details,success) "
                    "VALUES (?,?,?,?,?,?,?,0)",
                    (str(uuid.uuid4()), datetime.utcnow().isoformat(), str(event.user_id), "",
                     "qa.signoff.supersession_blocked", room_id,
                     json.dumps({"section_id": section_id, "reason": "missing supersession_reason"})),
                )
                return
            conn.execute(
                "INSERT INTO audit_log (log_id,timestamp,user_id,username,action,resource,details,success) "
                "VALUES (?,?,?,?,?,?,?,1)",
                (str(uuid.uuid4()), datetime.utcnow().isoformat(), str(event.user_id), "",
                 "qa.signoff.supersession", room_id,
                 json.dumps({"section_id": section_id, "reason": reason})),
            )
        conn.execute(
            "UPDATE roadworks_sections SET status='qa_approved', updated_at=? WHERE section_id=? AND room_id=?",
            (datetime.utcnow().isoformat(), section_id, room_id),
        )
    _trigger(event.room_id)


def _trigger(room_id: Any) -> None:
    try:
        from core.canary_engine import canary_engine
        canary_engine.compute(room_id)
    except Exception:
        pass