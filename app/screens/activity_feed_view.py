"""Activity Feed — live view wired to audit_service. Role-filtered."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)

from core.audit import audit_service
from core.models.user import User
from core.sdk.types import RoomId


class ActivityFeedView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: User | None = None
        self._room_id: RoomId | None = None
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        toolbar = QHBoxLayout()
        header = QLabel("Activity Feed")
        header.setFont(QFont("", 16, QFont.Bold))

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFixedHeight(34)
        refresh_btn.clicked.connect(self._refresh)

        toolbar.addWidget(header)
        toolbar.addStretch()
        toolbar.addWidget(refresh_btn)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.setSpacing(2)

        self._empty = QLabel("No activity recorded yet.")
        self._empty.setStyleSheet("color: #6c7086;")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.hide()

        layout.addLayout(toolbar)
        layout.addSpacing(8)
        layout.addWidget(self._list)
        layout.addWidget(self._empty)

    def _refresh(self) -> None:
        if not self._actor or not self._room_id:
            return

        self._list.clear()
        events = audit_service.query(self._room_id, self._actor, limit=200)

        if not events:
            self._empty.show()
            self._list.hide()
            return

        self._empty.hide()
        self._list.show()

        for ev in events:
            ts = ev["timestamp"][:16].replace("T", " ")
            text = f"{ts}   {ev['message']}"
            item = QListWidgetItem(text)
            item.setToolTip(f"Action: {ev['action']}\nBy: {ev['username']}")
            if not ev["success"]:
                item.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor("#f38ba8"))
            self._list.addItem(item)