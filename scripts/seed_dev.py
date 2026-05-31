#!/usr/bin/env python3
"""
scripts/seed_dev.py — Days 11/12 (final)

Full showcase scenario seed. All timestamps relative to datetime.now(timezone.utc).

Usage:
    PYTHONPATH=. python scripts/seed_dev.py          # seed only
    PYTHONPATH=. python scripts/seed_dev.py --reset  # drop DB then seed
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

NOW = datetime.now(timezone.utc).replace(tzinfo=None)

def ts(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()

def date_ago(days: int) -> str:
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%d")

def _uid(username: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, username))


# ---------------------------------------------------------------------------
# Kampala corridor waypoints
# ---------------------------------------------------------------------------
# 12km road, 6 sections × 2km, running north from Kampala city
WAYPOINTS = {
    "S1": [[0.300, 32.580], [0.309, 32.582], [0.318, 32.585]],
    "S2": [[0.318, 32.585], [0.327, 32.587], [0.336, 32.590]],
    "S3": [[0.336, 32.590], [0.345, 32.592], [0.354, 32.595]],
    "S4": [[0.354, 32.595], [0.363, 32.597], [0.372, 32.600]],
    "S5": [[0.372, 32.600], [0.381, 32.602], [0.390, 32.605]],
    "S6": [[0.390, 32.605], [0.399, 32.607], [0.408, 32.610]],
}

SECTIONS = [
    {"id": "S1", "label": "Section 1", "length_km": 2.0},
    {"id": "S2", "label": "Section 2", "length_km": 2.0},
    {"id": "S3", "label": "Section 3", "length_km": 2.0},
    {"id": "S4", "label": "Section 4", "length_km": 2.0},
    {"id": "S5", "label": "Section 5", "length_km": 2.0},
    {"id": "S6", "label": "Section 6", "length_km": 2.0},
]

SCENARIO = {
    "S1": {"status": "qa_approved", "km_paved": 2.0,  "checkin_hours_ago": 14},
    "S2": {"status": "qa_approved", "km_paved": 2.0,  "checkin_hours_ago": 22},
    "S3": {"status": "in_progress", "km_paved": 1.4,  "checkin_hours_ago": 51},
    "S4": {"status": "in_progress", "km_paved": 0.8,  "checkin_hours_ago": 31},
    "S5": {"status": "not_started", "km_paved": 0.0,  "checkin_hours_ago": None},
    "S6": {"status": "not_started", "km_paved": 0.0,  "checkin_hours_ago": None},
}

USERS = [
    ("admin",         "System Admin",      "Admin2026!",  True),
    ("pm_director",   "Grace Nakamura",    "Demo2026!",   True),
    ("analyst_1",     "David Osei",        "Demo2026!",   False),
    ("eng_lead",      "Moses Wandera",     "Demo2026!",   True),
    ("eng_officer",   "Priya Menon",       "Demo2026!",   False),
    ("proc_admin",    "Felix Ochieng",     "Demo2026!",   True),
    ("proc_officer",  "Amara Diallo",      "Demo2026!",   False),
    ("field_super",   "James Opio",        "Demo2026!",   True),
    ("field_officer", "Samuel Tukei",      "Demo2026!",   False),
    ("qa_lead",       "Sarah Nakato",      "Demo2026!",   True),
    ("qa_inspector",  "Daniel Ssemwanga",  "Demo2026!",   False),
]

ROOMS = [
    {"name": "Project Command",  "description": "Senior PM oversight",
     "members": [("pm_director","officer"),("analyst_1","viewer")],
     "sensors": []},
    {"name": "Engineering",      "description": "Site engineers — progress tracking",
     "members": [("eng_lead","officer"),("eng_officer","officer")],
     "sensors": ["roadworks.km_progress"]},
    {"name": "Procurement",      "description": "Materials acquisition and usage logs",
     "members": [("proc_admin","officer"),("proc_officer","officer")],
     "sensors": ["roadworks.materials_log"]},
    {"name": "Field Operations", "description": "Site supervisors — tasks and check-ins",
     "members": [("field_super","officer"),("field_officer","officer")],
     "sensors": ["roadworks.photo_checkin"]},
    {"name": "Quality Assurance","description": "Section inspection and sign-off",
     "members": [("qa_lead","officer"),("qa_inspector","officer")],
     "sensors": ["roadworks.qa_signoff"]},
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true",
                        help="Delete the database before seeding")
    args = parser.parse_args()

    if args.reset:
        db = Path("data/canary.db")
        if db.exists():
            db.unlink()
            print("Database deleted.")

    from core.db.schema import initialise_schema
    from core.db.connection import get_connection

    print("Initialising schema…")
    initialise_schema()

    _seed_users(get_connection)
    room_ids = _seed_rooms(get_connection)
    _install_roadworks(room_ids)
    _seed_sections(get_connection, room_ids)
    _seed_km_progress(get_connection, room_ids)
    _seed_materials(get_connection, room_ids)
    _seed_checkins(get_connection, room_ids)
    _seed_qa(get_connection, room_ids)
    _seed_tasks(get_connection, room_ids)
    _seed_notices(get_connection, room_ids)
    _seed_workflows(get_connection, room_ids)
    _compute_canary(room_ids)
    _enroll_totp(get_connection)

    print("\n✅  Seed complete.")
    print("   Scan totp_qr.png with your authenticator app.")
    print("   Login: pm_director / Demo2026!")


def _seed_users(gc) -> None:
    import bcrypt
    print("Seeding users…")
    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for username, display_name, password, is_admin in USERS:
            uid     = _uid(username)
            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            conn.execute(
                "INSERT OR IGNORE INTO users "
                "(user_id, username, display_name, password_hash, system_role, is_active, created_at) "
                "VALUES (?,?,?,?,?,1,?)",
                (uid, username, display_name, pw_hash,
                 "admin" if is_admin else "viewer", ts(24 * 60)),
            )
            conn.execute(
                "INSERT OR IGNORE INTO user_preferences "
                "(user_id, theme, font_size, colour_blind_mode, high_contrast, "
                " compute_interval_minutes, updated_at) VALUES (?,?,?,?,?,?,?)",
                (uid, "dark", "M", "none", 0, 5, ts(24 * 60)),
            )


def _seed_rooms(gc) -> dict[str, str]:
    print("Seeding rooms…")
    room_ids = {}
    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for room in ROOMS:
            rid = str(uuid.uuid5(uuid.NAMESPACE_DNS, room["name"]))
            room_ids[room["name"]] = rid
            conn.execute(
                "INSERT OR IGNORE INTO rooms "
                "(room_id, name, description, created_by, created_at) VALUES (?,?,?,?,?)",
                (rid, room["name"], room["description"], _uid("admin"), ts(24*60)),
            )
            for username, role in room["members"]:
                conn.execute(
                    "INSERT OR IGNORE INTO room_roles (user_id, room_id, role) VALUES (?,?,?)",
                    (_uid(username), rid, role),
                )
            conn.execute(
                "INSERT OR IGNORE INTO room_roles (user_id, room_id, role) VALUES (?,?,?)",
                (_uid("admin"), rid, "officer"),
            )
    return room_ids


def _install_roadworks(room_ids: dict) -> None:
    print("Installing RoadWorks…")
    from core.db.connection import get_connection
    from core.sensors.form_sensor import sensor_service
    from core.canary_engine import canary_engine
    from tools.roadworks.sensors import (
        KM_PROGRESS_SCHEMA, MATERIALS_SCHEMA, QA_SIGNOFF_SCHEMA,
        PHOTO_CHECKIN_SCHEMA, km_progress_callback, materials_callback, qa_signoff_callback,
    )
    from tools.roadworks.producers import progress_producer, materials_producer, rw_activity_producer

    config = json.dumps({"divergence_amber": 15.0, "divergence_red": 30.0, "stale_hours": 48})

    for room_name, rid in room_ids.items():
        room_cfg = next((r for r in ROOMS if r["name"] == room_name), {})
        sensors  = room_cfg.get("sensors", [])

        if not sensors:
            # Project Command — Canary producers only
            canary_engine.register_producer(rid, "roadworks.progress",  progress_producer)
            canary_engine.register_producer(rid, "roadworks.materials", materials_producer)
            canary_engine.register_producer(rid, "roadworks.activity",  rw_activity_producer)
            continue

        with get_connection() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                "INSERT OR IGNORE INTO installed_tools "
                "(room_id, tool_id, installed_by, installed_at, config) VALUES (?,?,?,?,?)",
                (rid, "roadworks", _uid("admin"), ts(24*60), config),
            )

        if "roadworks.km_progress"   in sensors: sensor_service.register("roadworks.km_progress",   rid, "Daily KM Progress",     KM_PROGRESS_SCHEMA,   "roadworks", km_progress_callback)
        if "roadworks.materials_log" in sensors: sensor_service.register("roadworks.materials_log", rid, "Materials Log",          MATERIALS_SCHEMA,     "roadworks", materials_callback)
        if "roadworks.qa_signoff"    in sensors: sensor_service.register("roadworks.qa_signoff",    rid, "QA Section Sign-off",    QA_SIGNOFF_SCHEMA,    "roadworks", qa_signoff_callback)
        if "roadworks.photo_checkin" in sensors: sensor_service.register("roadworks.photo_checkin", rid, "Site Photo Check-in",    PHOTO_CHECKIN_SCHEMA, "roadworks", None)

        canary_engine.register_producer(rid, "roadworks.progress",  progress_producer)
        canary_engine.register_producer(rid, "roadworks.materials", materials_producer)
        canary_engine.register_producer(rid, "roadworks.activity",  rw_activity_producer)


def _seed_sections(gc, room_ids: dict) -> None:
    print("Seeding sections with waypoints…")
    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for rid in room_ids.values():
            for s in SECTIONS:
                sc = SCENARIO[s["id"]]
                conn.execute(
                    "INSERT OR IGNORE INTO roadworks_sections "
                    "(section_id, room_id, label, length_km, status, waypoints, updated_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (s["id"], rid, s["label"], s["length_km"], sc["status"],
                     json.dumps(WAYPOINTS[s["id"]]), ts(2)),
                )


def _seed_km_progress(gc, room_ids: dict) -> None:
    print("Seeding KM progress…")
    eng_rid = room_ids.get("Engineering", list(room_ids.values())[0])
    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for sid, sc in SCENARIO.items():
            km = sc["km_paved"]
            if km <= 0:
                continue
            cumulative = 0.0
            for day_ago in range(56, 0, -1):
                if cumulative >= km:
                    break
                daily = round(min(0.25, round(km - cumulative, 2)), 2)
                if daily <= 0:
                    break
                eid      = str(uuid.uuid4())
                date_str = (NOW - timedelta(days=day_ago)).strftime("%Y-%m-%d")
                cumulative = round(cumulative + daily, 2)
                conn.execute(
                    "INSERT OR IGNORE INTO sensor_events "
                    "(event_id, sensor_id, room_id, user_id, timestamp, payload) VALUES (?,?,?,?,?,?)",
                    (eid, "roadworks.km_progress", eng_rid, _uid("eng_officer"),
                     ts(day_ago * 24), json.dumps({"section_id": sid, "km_paved": daily, "date": date_str})),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO roadworks_km_progress "
                    "(event_id, section_id, room_id, km_paved, date, cumulative_km) VALUES (?,?,?,?,?,?)",
                    (eid, sid, eng_rid, daily, date_str, cumulative),
                )


def _seed_materials(gc, room_ids: dict) -> None:
    print("Seeding materials (S3 at 40% divergence)…")
    proc_rid = room_ids.get("Procurement", list(room_ids.values())[0])
    rows = [
        ("S1", "aggregate", 200.0, 204.0, "tonnes", 14),
        ("S2", "bitumen",    50.0,  54.0, "tonnes", 10),
        ("S3", "aggregate", 120.0, 168.0, "tonnes",  5),
        ("S4", "aggregate",  80.0,  89.6, "tonnes",  3),
    ]
    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for sid, material, acquired, consumed, unit, days in rows:
            eid = str(uuid.uuid4())
            div = round((consumed - acquired) / acquired * 100, 2)
            conn.execute(
                "INSERT OR IGNORE INTO sensor_events "
                "(event_id, sensor_id, room_id, user_id, timestamp, payload) VALUES (?,?,?,?,?,?)",
                (eid, "roadworks.materials_log", proc_rid, _uid("proc_officer"),
                 ts(days * 24), json.dumps({"section_id": sid, "material": material,
                     "quantity_acquired": acquired, "quantity_consumed": consumed,
                     "unit": unit, "date": date_ago(days)})),
            )
            conn.execute(
                "INSERT OR IGNORE INTO roadworks_materials "
                "(event_id, section_id, room_id, material, quantity_acquired, "
                " quantity_consumed, unit, date, divergence_pct) VALUES (?,?,?,?,?,?,?,?,?)",
                (eid, sid, proc_rid, material, acquired, consumed, unit, date_ago(days), div),
            )


def _seed_checkins(gc, room_ids: dict) -> None:
    print("Seeding photo check-ins…")
    field_rid = room_ids.get("Field Operations", list(room_ids.values())[0])
    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for sid, sc in SCENARIO.items():
            if sc["checkin_hours_ago"] is None:
                continue
            eid     = str(uuid.uuid4())
            wp      = WAYPOINTS[sid][1]   # midpoint waypoint
            gps_lat = wp[0]
            gps_lon = wp[1]
            conn.execute(
                "INSERT OR IGNORE INTO sensor_events "
                "(event_id, sensor_id, room_id, user_id, timestamp, payload) VALUES (?,?,?,?,?,?)",
                (eid, "roadworks.photo_checkin", field_rid, _uid("field_officer"),
                 ts(sc["checkin_hours_ago"]),
                 json.dumps({"entity_id": sid, "gps_lat": gps_lat, "gps_lon": gps_lon})),
            )
            conn.execute(
                "INSERT OR IGNORE INTO photo_checkins "
                "(event_id, entity_id, photo_path, gps_lat, gps_lon) VALUES (?,?,?,?,?)",
                (eid, sid, None, gps_lat, gps_lon),
            )


def _seed_qa(gc, room_ids: dict) -> None:
    print("Seeding QA approvals (S1, S2 with supersession)…")
    qa_rid = room_ids.get("Quality Assurance", list(room_ids.values())[0])
    events = [
        {"section_id":"S1","approved":True,"inspector_name":"Daniel Ssemwanga",
         "inspection_date":date_ago(18),"notes":"Meets specification",
         "supersession_reason":None,"hours_ago":18*24,"user":"qa_inspector"},
        {"section_id":"S2","approved":True,"inspector_name":"Daniel Ssemwanga",
         "inspection_date":date_ago(16),"notes":"Minor surface cracks noted",
         "supersession_reason":None,"hours_ago":16*24,"user":"qa_inspector"},
        {"section_id":"S2","approved":True,"inspector_name":"Sarah Nakato",
         "inspection_date":date_ago(11),"notes":"Re-inspected after rainfall. Passed.",
         "supersession_reason":"Re-inspection required after rainfall damage",
         "hours_ago":11*24,"user":"qa_lead"},
    ]
    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for ev in events:
            eid     = str(uuid.uuid4())
            payload = {k: v for k, v in ev.items() if k not in ("hours_ago","user")}
            conn.execute(
                "INSERT OR IGNORE INTO sensor_events "
                "(event_id, sensor_id, room_id, user_id, timestamp, payload) VALUES (?,?,?,?,?,?)",
                (eid, "roadworks.qa_signoff", qa_rid, _uid(ev["user"]),
                 ts(ev["hours_ago"]), json.dumps(payload)),
            )


def _seed_tasks(gc, room_ids: dict) -> None:
    print("Seeding tasks…")
    tasks = [
        {"room":"Field Operations","title":"Install safety barriers — Section 4",
         "assigned_to":"field_officer","due_hours_ago":72,"tags":{"section_id":"S4"}},
        {"room":"Engineering","title":"Submit progress report — Week 8",
         "assigned_to":"eng_officer","due_hours_ago":24,"tags":None},
        {"room":"Procurement","title":"Reconcile S3 aggregate records",
         "assigned_to":"proc_officer","due_hours_ago":-48,"tags":{"section_id":"S3"}},
        {"room":"Engineering","title":"Lay base course — Section 5",
         "assigned_to":"eng_officer","due_hours_ago":-120,"tags":{"section_id":"S5"}},
    ]
    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for t in tasks:
            rid = room_ids.get(t["room"])
            if not rid:
                continue
            hours  = t["due_hours_ago"]
            due_at = ((NOW - timedelta(hours=abs(hours))).isoformat() if hours > 0
                      else (NOW + timedelta(hours=abs(hours))).isoformat())
            conn.execute(
                "INSERT OR IGNORE INTO tasks "
                "(task_id, room_id, title, description, status, assigned_to, "
                " created_by, created_at, due_at, tags) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), rid, t["title"], "", "open",
                 _uid(t["assigned_to"]), _uid("admin"), ts(7*24), due_at,
                 json.dumps(t["tags"]) if t["tags"] else None),
            )


def _seed_notices(gc, room_ids: dict) -> None:
    print("Seeding notices…")
    notices = [
        {"room":"Field Operations","title":"Site safety protocols updated",
         "content":"Updated hard hat and safety vest requirements apply from Monday.",
         "pinned":True,"expires_hours":None},
        {"room":"Engineering","title":"Week 8 progress review — Engineering team",
         "content":"Progress review meeting scheduled. All officers to attend.",
         "pinned":False,"expires_hours":24},
        {"room":"Procurement","title":"Materials reconciliation — S1 and S2 complete",
         "content":"Reconciliation signed off by Finance.",
         "pinned":False,"expires_hours":-48},   # already expired
    ]
    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for n in notices:
            rid = room_ids.get(n["room"])
            if not rid:
                continue
            expires_at = None
            if n["expires_hours"] is not None:
                expires_at = (NOW + timedelta(hours=n["expires_hours"])).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO notices "
                "(notice_id, room_id, title, message, posted_by, posted_at, "
                " is_pinned, expires_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), rid, n["title"], n["content"],
                 _uid("admin"), ts(2), 1 if n["pinned"] else 0, expires_at),
            )


def _seed_workflows(gc, room_ids: dict) -> None:
    print("Seeding workflow instances…")
    eng_rid  = room_ids.get("Engineering", list(room_ids.values())[0])
    proc_rid = room_ids.get("Procurement", list(room_ids.values())[0])

    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")

        # Instance 1 — active, currently at fulfillment (step 3)
        iid1 = str(uuid.uuid4())
        conn.execute(
            "INSERT OR IGNORE INTO workflow_instances "
            "(instance_id, room_id, workflow_id, title, current_step_id, "
            " current_step_label, initiated_by, started_at, status, workflow_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (iid1, eng_rid, "wf-procurement-001",
             "Tarmac Materials Q2 — Phase 2 Order",
             "fulfillment", "Order Fulfillment",
             _uid("eng_lead"), ts(5*24), "active", "Standard Procurement"),
        )

        # Instance 2 — stalled at approval (SLA exceeded 3 days ago)
        iid2 = str(uuid.uuid4())
        conn.execute(
            "INSERT OR IGNORE INTO workflow_instances "
            "(instance_id, room_id, workflow_id, title, current_step_id, "
            " current_step_label, initiated_by, started_at, status, workflow_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (iid2, proc_rid, "wf-procurement-001",
             "Aggregate Procurement — Emergency S3 Resupply",
             "approval", "Awaiting Finance Approval",
             _uid("proc_admin"), ts(9*24), "stalled", "Standard Procurement"),
        )

        # Seed workflow steps for both rooms if not already present
        for rid in (eng_rid, proc_rid):
            for sid, label, role, order, terminal, sla in [
                ("request",      "Procurement Request",       "officer", 1, 0, 24),
                ("approval",     "Awaiting Finance Approval", "officer", 2, 0, 48),
                ("fulfillment",  "Order Fulfillment",         "officer", 3, 0, 72),
                ("confirmation", "Fulfillment Confirmation",  "officer", 4, 1, 24),
            ]:
                conn.execute(
                    "INSERT OR IGNORE INTO workflow_steps "
                    "(step_id, workflow_id, room_id, label, required_role, "
                    " step_order, is_terminal, sla_hours) VALUES (?,?,?,?,?,?,?,?)",
                    (sid, "wf-procurement-001", rid, label, role, order, terminal, sla),
                )


def _compute_canary(room_ids: dict) -> None:
    print("Computing Canary for all rooms…")
    from core.canary_engine import canary_engine
    for rid in room_ids.values():
        try:
            canary_engine.compute(rid)
        except Exception as exc:
            print(f"  Warning: {rid}: {exc}")


def _enroll_totp(gc) -> None:
    print("Enrolling TOTP for pm_director…")
    import pyotp, qrcode
    uid    = _uid("pm_director")
    secret = pyotp.random_base32()
    with gc() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("UPDATE users SET totp_secret=? WHERE user_id=?", (secret, uid))
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name="pm_director", issuer_name="Sudo Canary")
    qrcode.make(uri).save("totp_qr.png")
    print("   Saved totp_qr.png")


if __name__ == "__main__":
    main()