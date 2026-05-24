"""
app/screens/documents.py

Documents tab — live.

Left panel: document list (name, version, last updated).
Right panel: version history for selected document.
Upload button opens QFileDialog. Download copies file to user-chosen path.
Checksum mismatch shows red banner.

Role gate:
  Viewer: read and download only.
  Officer and above: can also upload.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QVBoxLayout, QWidget, QLineEdit, QDialog, QFormLayout, QDialogButtonBox,
)

from core.auth.rbac import can_manage_room, require_room_access
from core.documents.document_impl import ChecksumMismatch, document_service
from core.models.user import User
from core.sdk.types import Document, DocumentId, RoomId


class _UploadDialog(QDialog):
    def __init__(self, file_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Upload Document")
        self.setMinimumWidth(420)
        self._file_path = file_path
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_input = QLineEdit()
        p = Path(self._file_path)
        self._name_input.setText(p.name)
        self._name_input.setPlaceholderText("Document name")

        self._notes_input = QLineEdit()
        self._notes_input.setPlaceholderText("Optional version notes")

        form.addRow("Document name *", self._name_input)
        form.addRow("Notes", self._notes_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout.addWidget(QLabel(f"File: {Path(self._file_path).name}"))
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        if not self._name_input.text().strip():
            QMessageBox.warning(self, "Required", "Document name is required.")
            return
        self.accept()

    def values(self) -> tuple[str, str]:
        return self._name_input.text().strip(), self._notes_input.text().strip()


class DocumentsView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: Optional[User] = None
        self._room_id: Optional[RoomId] = None
        self._documents: List[Document] = []
        self._selected: Optional[Document] = None
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        is_officer = can_manage_room(actor, room_id)
        self._upload_btn.setVisible(is_officer)
        self._refresh_list()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        # Left panel
        left = QWidget()
        left.setFixedWidth(260)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 8, 12)

        header = QLabel("Documents")
        header.setFont(QFont("", 13, QFont.Bold))

        self._upload_btn = QPushButton("⬆  Upload")
        self._upload_btn.setFixedHeight(32)
        self._upload_btn.setVisible(False)
        self._upload_btn.clicked.connect(self._upload)

        self._doc_list = QListWidget()
        self._doc_list.currentRowChanged.connect(self._on_doc_selected)

        ll.addWidget(header)
        ll.addWidget(self._upload_btn)
        ll.addWidget(self._doc_list)

        # Right panel
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 12, 16, 12)

        self._doc_title = QLabel("Select a document")
        self._doc_title.setFont(QFont("", 14, QFont.Bold))

        versions_group = QGroupBox("Version history")
        vl = QVBoxLayout(versions_group)
        self._version_table = QTableWidget(0, 5)
        self._version_table.setHorizontalHeaderLabels(
            ["Version", "Uploaded by", "Date", "Notes", ""]
        )
        self._version_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._version_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._version_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._version_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._version_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._version_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._version_table.verticalHeader().hide()
        vl.addWidget(self._version_table)

        rl.addWidget(self._doc_title)
        rl.addWidget(versions_group)
        rl.addStretch()

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([260, 580])
        layout.addWidget(splitter)

    # ── Document list ─────────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self._doc_list.clear()
        self._documents = document_service.list_documents(self._actor, self._room_id)

        if not self._documents:
            item = QListWidgetItem("No documents uploaded yet.")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self._doc_list.addItem(item)
            self.status_message.emit("No documents")
            return

        for doc in self._documents:
            cv = doc.current_version
            date_str = cv.uploaded_at.strftime("%Y-%m-%d") if cv else "—"
            item = QListWidgetItem(f"{doc.name}\nv{len(doc.versions)}  ·  {date_str}")
            self._doc_list.addItem(item)

        self.status_message.emit(f"{len(self._documents)} document(s)")

    def _on_doc_selected(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._documents):
            return
        self._selected = self._documents[idx]
        self._refresh_version_table()

    def _refresh_version_table(self) -> None:
        doc = self._selected
        if not doc:
            return
        self._doc_title.setText(doc.name)
        self._version_table.setRowCount(0)

        # Load display names for uploaders
        from core.db.connection import get_connection
        with get_connection() as conn:
            uploaders = {}
            for v in doc.versions:
                row = conn.execute(
                    "SELECT display_name FROM users WHERE user_id = ?",
                    (str(v.uploaded_by),),
                ).fetchone()
                uploaders[str(v.uploaded_by)] = row["display_name"] if row else str(v.uploaded_by)

        for v in reversed(doc.versions):  # newest first
            r = self._version_table.rowCount()
            self._version_table.insertRow(r)
            self._version_table.setItem(r, 0, QTableWidgetItem(f"v{v.version}"))
            self._version_table.setItem(r, 1, QTableWidgetItem(uploaders.get(str(v.uploaded_by), "?")))
            self._version_table.setItem(r, 2, QTableWidgetItem(v.uploaded_at.strftime("%Y-%m-%d %H:%M")))
            self._version_table.setItem(r, 3, QTableWidgetItem(v.notes or "—"))

            dl_btn = QPushButton("⬇ Download")
            dl_btn.setFixedHeight(28)
            version_num = v.version
            doc_id = doc.document_id
            dl_btn.clicked.connect(
                lambda _, d=doc_id, v=version_num: self._download(d, v)
            )
            self._version_table.setCellWidget(r, 4, dl_btn)

    # ── Upload ────────────────────────────────────────────────────────────────

    def _upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select file", "",
            "Documents (*.pdf *.docx *.xlsx *.png *.jpg *.jpeg)"
        )
        if not path:
            return

        dlg = _UploadDialog(path, self)
        if dlg.exec() != QDialog.Accepted:
            return
        name, notes = dlg.values()

        try:
            doc = document_service.upload(
                self._actor, self._room_id, name, path, notes
            )
            self._refresh_list()
            self.status_message.emit(f"Uploaded: {name}")
            top = self.window()
            if hasattr(top, "_banner_bar"):
                top._banner_bar.show_banner(f"Document uploaded: {name}", kind="success")
        except Exception as exc:
            QMessageBox.critical(self, "Upload failed", str(exc))

    # ── Download ──────────────────────────────────────────────────────────────

    def _download(self, document_id: DocumentId, version: int) -> None:
        dest, _ = QFileDialog.getSaveFileName(self, "Save file as")
        if not dest:
            return
        try:
            document_service.download(
                self._actor, self._room_id, document_id, version, dest
            )
            self.status_message.emit("File downloaded")
        except ChecksumMismatch as exc:
            top = self.window()
            if hasattr(top, "_banner_bar"):
                top._banner_bar.show_banner(str(exc), kind="error")
        except Exception as exc:
            QMessageBox.critical(self, "Download failed", str(exc))