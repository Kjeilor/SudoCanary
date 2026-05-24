"""
core/documents/document_impl.py

DocumentService: upload, version, list, and download documents.

Storage layout: data/documents/{room_id}/{document_id}_v{version}_{safe_name}

Upload and audit_log write share one DB connection — atomic.
Checksum (SHA-256) computed on upload, verified on download.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.auth.rbac import require_officer, require_room_access
from core.db.connection import get_connection
from core.models.user import User
from core.sdk.types import (
    ActionType,
    Document,
    DocumentId,
    DocumentVersion,
    RoomId,
    UserId,
)

STORAGE_BASE = Path("data/documents")
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg"}


def _safe_name(name: str) -> str:
    """Strip unsafe characters from a filename component."""
    return re.sub(r"[^\w\-.]", "_", name)[:80]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class ChecksumMismatch(Exception):
    pass


class DocumentService:

    # ── Upload ────────────────────────────────────────────────────────────────

    def upload(
        self,
        actor: User,
        room_id: RoomId,
        name: str,
        source_path: str | Path,
        notes: str = "",
    ) -> Document:
        """
        Copy source_path into the document store, create or version the record.
        Upload requires Field Officer role or above.
        Raises ValueError for disallowed file extensions.
        """
        require_officer(actor, room_id)

        source = Path(source_path)
        ext = source.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(
                f"Extension '{ext}' is not allowed. "
                f"Permitted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        now = datetime.utcnow()

        with get_connection() as conn:
            # Check if document with this name already exists in the room
            existing = conn.execute(
                "SELECT document_id FROM documents WHERE room_id = ? AND name = ?",
                (str(room_id), name),
            ).fetchone()

            if existing:
                doc_id = existing["document_id"]
                version_row = conn.execute(
                    "SELECT MAX(version) FROM document_versions WHERE document_id = ?",
                    (doc_id,),
                ).fetchone()
                version = (version_row[0] or 0) + 1
                action = ActionType.DOCUMENT_VERSIONED
            else:
                doc_id = str(uuid.uuid4())
                version = 1
                action = ActionType.DOCUMENT_UPLOADED
                conn.execute(
                    "INSERT INTO documents (document_id, room_id, name, created_at) VALUES (?, ?, ?, ?)",
                    (doc_id, str(room_id), name, now.isoformat()),
                )

            # Copy file
            dest_dir = STORAGE_BASE / str(room_id)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_name = f"{doc_id}_v{version}_{_safe_name(source.name)}"
            dest_path = dest_dir / dest_name
            shutil.copy2(source, dest_path)
            checksum = _sha256(dest_path)

            conn.execute(
                """INSERT INTO document_versions
                   (document_id, version, uploaded_by, uploaded_at, file_path, checksum, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc_id, version, str(actor.user_id),
                    now.isoformat(), str(dest_path), checksum, notes,
                ),
            )
            conn.execute(
                """INSERT INTO audit_log
                   (log_id, timestamp, user_id, username, action, resource, details, success)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    str(uuid.uuid4()), now.isoformat(),
                    str(actor.user_id), actor.username,
                    action.value, str(room_id),
                    json.dumps({"name": name, "version": version, "document_id": doc_id}),
                ),
            )

        return self.get_document(actor, room_id, DocumentId(doc_id))

    # ── Read ──────────────────────────────────────────────────────────────────

    def list_documents(self, actor: User, room_id: RoomId) -> List[Document]:
        require_room_access(actor, room_id)
        with get_connection() as conn:
            doc_rows = conn.execute(
                "SELECT * FROM documents WHERE room_id = ? ORDER BY name",
                (str(room_id),),
            ).fetchall()
        return [
            self._load_document(doc["document_id"])
            for doc in doc_rows
        ]

    def get_document(
        self, actor: User, room_id: RoomId, document_id: DocumentId
    ) -> Document:
        require_room_access(actor, room_id)
        return self._load_document(str(document_id))

    def _load_document(self, document_id: str) -> Document:
        with get_connection() as conn:
            doc_row = conn.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document_id,)
            ).fetchone()
            if not doc_row:
                raise ValueError(f"Document '{document_id}' not found")
            ver_rows = conn.execute(
                "SELECT * FROM document_versions WHERE document_id = ? ORDER BY version",
                (document_id,),
            ).fetchall()

        versions = tuple(
            DocumentVersion(
                version=r["version"],
                uploaded_by=UserId(r["uploaded_by"]),
                uploaded_at=datetime.fromisoformat(r["uploaded_at"]),
                file_path=r["file_path"],
                checksum=r["checksum"],
                notes=r["notes"],
            )
            for r in ver_rows
        )
        return Document(
            document_id=DocumentId(doc_row["document_id"]),
            room_id=RoomId(doc_row["room_id"]),
            name=doc_row["name"],
            versions=versions,
        )

    # ── Download ──────────────────────────────────────────────────────────────

    def download(
        self,
        actor: User,
        room_id: RoomId,
        document_id: DocumentId,
        version: int,
        dest_path: str | Path,
    ) -> None:
        """
        Copy a document version to dest_path.
        Verifies SHA-256 checksum before writing. Raises ChecksumMismatch on failure.
        All roles with room access can download.
        """
        require_room_access(actor, room_id)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM document_versions WHERE document_id = ? AND version = ?",
                (str(document_id), version),
            ).fetchone()

        if not row:
            raise ValueError(f"Version {version} of document '{document_id}' not found")

        src = Path(row["file_path"])
        if not src.exists():
            raise FileNotFoundError(f"Stored file missing: {src}")

        live_checksum = _sha256(src)
        if live_checksum != row["checksum"]:
            raise ChecksumMismatch(
                f"Checksum mismatch for document '{document_id}' v{version}. "
                "The file may have been tampered with."
            )

        shutil.copy2(src, dest_path)


document_service = DocumentService()