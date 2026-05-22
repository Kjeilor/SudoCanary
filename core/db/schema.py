"""
Database schema initialisation. Called once at application startup.
All tables are append-only where possible — mutations via UPDATE only for
mutable state fields (last_login, is_active, totp_secret, first_login_complete).
Every destructive action goes through the audit_log instead.
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
    log_id      TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL,
    user_id     TEXT,
    username    TEXT,
    action      TEXT NOT NULL,
    resource    TEXT,
    details     TEXT,
    success     INTEGER NOT NULL DEFAULT 1
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

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_notices_room ON notices(room_id, pinned, created_at);
"""


def initialise_schema() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)