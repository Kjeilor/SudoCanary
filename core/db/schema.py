"""
Database schema initialisation.

Day 3: audit_log uses seq INTEGER PRIMARY KEY AUTOINCREMENT.
Day 4: sensors, sensor_events, documents, document_versions,
       workflow_instances tables added. expires_at added to notices
       via idempotent ALTER TABLE migration.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from core.db.connection import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id                 TEXT PRIMARY KEY,
    username                TEXT UNIQUE NOT NULL,
    display_name            TEXT NOT NULL,
    password_hash           TEXT NOT NULL,
    system_role             TEXT,
    totp_secret             TEXT,
    is_active               INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL,
    last_login              TEXT,
    first_login_complete    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS room_roles (
    user_id     TEXT NOT NULL REFERENCES users(user_id),
    room_id     TEXT NOT NULL,
    role        TEXT NOT NULL CHECK(role IN ('officer', 'viewer')),
    PRIMARY KEY (user_id, room_id)
);

CREATE TABLE IF NOT EXISTS rooms (
    room_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    created_by  TEXT NOT NULL REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    log_id      TEXT UNIQUE NOT NULL,
    timestamp   TEXT NOT NULL,
    user_id     TEXT,
    username    TEXT,
    action      TEXT NOT NULL,
    resource    TEXT,
    details     TEXT,
    success     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES rooms(room_id),
    title           TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    created_by      TEXT NOT NULL REFERENCES users(user_id),
    created_at      TEXT NOT NULL,
    trackability    TEXT NOT NULL DEFAULT 'trackable'
                    CHECK(trackability IN ('trackable', 'untrackable')),
    assigned_to     TEXT REFERENCES users(user_id),
    due_at          TEXT,
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK(status IN ('open', 'in_progress', 'complete', 'cancelled')),
    parent_task_id  TEXT REFERENCES tasks(task_id)
);

CREATE TABLE IF NOT EXISTS notices (
    notice_id   TEXT PRIMARY KEY,
    room_id     TEXT NOT NULL REFERENCES rooms(room_id),
    author_id   TEXT NOT NULL REFERENCES users(user_id),
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    pinned      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    expires_at  TEXT
);

CREATE TABLE IF NOT EXISTS data_notice_acceptances (
    user_id         TEXT PRIMARY KEY REFERENCES users(user_id),
    accepted_at     TEXT NOT NULL,
    notice_version  TEXT NOT NULL DEFAULT '1.0'
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id           TEXT PRIMARY KEY REFERENCES users(user_id),
    theme             TEXT NOT NULL DEFAULT 'dark'
                      CHECK(theme IN ('light', 'dark', 'system')),
    font_size         TEXT NOT NULL DEFAULT 'M'
                      CHECK(font_size IN ('S', 'M', 'L', 'XL')),
    colour_blind_mode TEXT NOT NULL DEFAULT 'none'
                      CHECK(colour_blind_mode IN
                        ('none','deuteranopia','protanopia','tritanopia','monochromacy')),
    high_contrast     INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sensors (
    sensor_id   TEXT NOT NULL,
    room_id     TEXT NOT NULL,
    tool_id     TEXT,
    label       TEXT NOT NULL,
    schema_json TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (sensor_id, room_id)
);

CREATE TABLE IF NOT EXISTS sensor_events (
    event_id    TEXT PRIMARY KEY,
    room_id     TEXT NOT NULL,
    sensor_id   TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    payload     TEXT NOT NULL,
    provenance  TEXT NOT NULL,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id)
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    room_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id)
);

CREATE TABLE IF NOT EXISTS document_versions (
    document_id TEXT NOT NULL,
    version     INTEGER NOT NULL,
    uploaded_by TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    notes       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (document_id, version),
    FOREIGN KEY (document_id) REFERENCES documents(document_id)
);

CREATE TABLE IF NOT EXISTS workflow_instances (
    instance_id        TEXT PRIMARY KEY,
    workflow_id        TEXT NOT NULL,
    room_id            TEXT NOT NULL REFERENCES rooms(room_id),
    title              TEXT NOT NULL,
    current_step_id    TEXT NOT NULL,
    current_step_label TEXT NOT NULL,
    initiated_by       TEXT NOT NULL REFERENCES users(user_id),
    started_at         TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'active'
                       CHECK(status IN ('active','complete','cancelled','stalled')),
    parent_template    TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp    ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user         ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_resource     ON audit_log(resource, seq);
CREATE INDEX IF NOT EXISTS idx_tasks_room         ON tasks(room_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned     ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_notices_room       ON notices(room_id, pinned, created_at);
CREATE INDEX IF NOT EXISTS idx_sensor_events_room ON sensor_events(room_id, sensor_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_workflow_room      ON workflow_instances(room_id, status);
"""


def _migrate(conn) -> None:
    """Idempotent column migrations for databases created before Day 4."""
    try:
        conn.execute("ALTER TABLE notices ADD COLUMN expires_at TEXT")
    except Exception:
        pass  # column already present


def initialise_schema() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.executescript(_SCHEMA_DAY5)
        _migrate(conn)
    seed_demo_workflows()


def seed_demo_workflows() -> None:
    """
    Insert two realistic RoadWorks demo workflow instances.

    Guards:
      - At least one room must exist (uses its room_id)
      - At least one user must exist (uses as initiated_by)
      - workflow_instances table must be empty

    Skips silently on a fresh installation with no real data.
    """
    with get_connection() as conn:
        room_row = conn.execute("SELECT room_id FROM rooms LIMIT 1").fetchone()
        user_row = conn.execute("SELECT user_id FROM users LIMIT 1").fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM workflow_instances"
        ).fetchone()[0]

        if not room_row or not user_row or count > 0:
            return

        room_id = room_row["room_id"]
        user_id = user_row["user_id"]
        now = datetime.utcnow()

        instances = [
            (
                str(uuid.uuid4()),
                "wf-procurement-001",
                room_id,
                "Procurement Request — Tarmac Materials Q2",
                "approval",
                "Awaiting Finance Approval",
                user_id,
                (now - timedelta(days=3)).isoformat(),
                "stalled",
                "Procurement Workflow v1",
            ),
            (
                str(uuid.uuid4()),
                "wf-inspection-001",
                room_id,
                "Section 4A Site Inspection",
                "field_report",
                "Field Officer Submission",
                user_id,
                (now - timedelta(days=1)).isoformat(),
                "active",
                "Road Inspection Workflow v1",
            ),
        ]

        conn.executemany(
            """INSERT INTO workflow_instances
               (instance_id, workflow_id, room_id, title, current_step_id,
                current_step_label, initiated_by, started_at, status, parent_template)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            instances,
        )

# Called from initialise_schema — adds photo_checkins table
_SCHEMA_DAY5 = """
CREATE TABLE IF NOT EXISTS photo_checkins (
    event_id    TEXT PRIMARY KEY REFERENCES sensor_events(event_id),
    entity_id   TEXT NOT NULL,
    photo_path  TEXT NOT NULL,
    gps_lat     REAL,
    gps_lon     REAL,
    timestamp   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_checkins_entity
    ON photo_checkins(entity_id, timestamp DESC);
"""