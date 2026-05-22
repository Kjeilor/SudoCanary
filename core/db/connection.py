"""
SQLCipher-encrypted database connection factory.

Key is stored in data/.db_key for the prototype.
BEFORE SHOWCASE: replace _get_db_key() with macOS Keychain lookup
via the `keyring` package: keyring.get_password("SudoCanary", "db_key")
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

try:
    from sqlcipher3 import dbapi2 as sqlite
except ImportError as exc:
    raise ImportError(
        "sqlcipher3 is required.\n"
        "  brew install sqlcipher\n"
        "  pip install sqlcipher3"
    ) from exc

DB_PATH = Path("data/canary.db")
_KEY_PATH = Path("data/.db_key")


def _get_db_key() -> str:
    """Retrieve or generate the AES-256 database encryption key."""
    if _KEY_PATH.exists():
        return _KEY_PATH.read_text().strip()
    key = os.urandom(32).hex()
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _KEY_PATH.write_text(key)
    # TODO (pre-showcase): store in macOS Keychain instead of flat file
    return key


@contextmanager
def get_connection() -> Generator[sqlite.Connection, None, None]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite.connect(str(DB_PATH))
    try:
        conn.execute(f"PRAGMA key='{_get_db_key()}'")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite.Row
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()