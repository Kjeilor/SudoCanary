"""
Database schema initialisation.

Day 3 breaking change: audit_log now uses seq INTEGER PRIMARY KEY AUTOINCREMENT.
If upgrading from a Day 2 database, delete data/canary.db before running.
"""
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
    created_at  TEXT NOT NULL
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

CREATE INDEX IF NOT EXISTS idx_audit_timestamp  ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user       ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_resource   ON audit_log(resource, seq);
CREATE INDEX IF NOT EXISTS idx_tasks_room       ON tasks(room_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned   ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_notices_room     ON notices(room_id, pinned, created_at);
"""


def initialise_schema() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)