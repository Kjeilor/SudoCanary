"""
app/screens/staging.py

Staging area — shown after MFA, before entering a room.
Displays accessible rooms as cards: name, role, canary status (grey until
Day 6 engine), active task count, overdue count highlighted amber.

Emits:
  room_selected(room_id: str, room_name: str)  — user clicked a card
  settings_requested()                          — gear icon clicked
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QScrollArea, QVBoxLayout, QWidget,
)

from core.auth.rbac import get_room_role
from core.models.user import User
from core.room_impl import RoomAPIImpl
from core.sdk.types import RoomId

_STATUS_COLOUR = {
    "green": "#a6e3a1",
    "amber": "#f9e2af",
    "red":   "#f38ba8",
    "grey":  "#6c7086",
}


class _RoomCard(QFrame):
    clicked = Signal(str, str)  # room_id, room_name

    def __init__(self, room: dict, actor: User, parent=None) -> None:
        super().__init__(parent)
        self._room_id   = room["room_id"]
        self._room_name = room["name"]
        self.setFixedSize(230, 150)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QFrame { background-color: #181825; border-radius: 10px; }"
            "QFrame:hover { background-color: #24243e; }"
        )
        self._build(room, actor)

    def _build(self, room: dict, actor: User) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        # Room name
        name = QLabel(room["name"])
        name.setFont(QFont("", 13, QFont.Bold))
        name.setWordWrap(True)

        # Role badge
        role = get_room_role(actor, RoomId(room["room_id"]))
        role_text = role.value.replace("_", " ").title() if role else "No role"
        role_label = QLabel(role_text)
        role_label.setStyleSheet("color: #a6adc8; font-size: 12px;")

        # Canary status — grey until Day 6
        canary_row = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {_STATUS_COLOUR['grey']};")
        status_lbl = QLabel("Pending")
        status_lbl.setStyleSheet("color: #6c7086; font-size: 12px;")
        canary_row.addWidget(dot)
        canary_row.addWidget(status_lbl)
        canary_row.addStretch()

        # Task counts
        task_label = self._task_summary(actor, room["room_id"])

        layout.addWidget(name)
        layout.addWidget(role_label)
        layout.addStretch()
        layout.addLayout(canary_row)
        layout.addWidget(task_label)

    def _task_summary(self, actor: User, room_id: str) -> QLabel:
        try:
            from core.task_impl import task_service
            counts = task_service.count_by_status(actor, RoomId(room_id))
            text = f"{counts['active']} active"
            if counts["overdue"]:
                text += f"  ·  {counts['overdue']} overdue"
            lbl = QLabel(text)
            if counts["overdue"]:
                lbl.setStyleSheet("color: #f9e2af; font-size: 12px;")
            else:
                lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")
        except Exception:
            lbl = QLabel("No tasks")
            lbl.setStyleSheet("color: #6c7086; font-size: 12px;")
        return lbl

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._room_id, self._room_name)
        super().mousePressEvent(event)


class StagingArea(QWidget):
    room_selected      = Signal(str, str)   # room_id, room_name
    settings_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 36, 48, 36)
        layout.setSpacing(16)

        header = QLabel("Your Rooms")
        header.setFont(QFont("", 20, QFont.Bold))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(20)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(self._grid_widget)

        self._empty_label = QLabel(
            "You have no rooms yet.\n"
            "Ask your administrator to add you to a room."
        )
        self._empty_label.setStyleSheet("color: #6c7086;")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.hide()

        layout.addWidget(header)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(self._empty_label)

    def load_rooms(self, actor: User) -> None:
        # Clear existing cards
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rooms = RoomAPIImpl(actor).list_rooms()

        if not rooms:
            self._empty_label.show()
            return

        self._empty_label.hide()
        cols = 4
        for i, room in enumerate(rooms):
            card = _RoomCard(room, actor)
            card.clicked.connect(self.room_selected)
            self._grid.addWidget(card, i // cols, i % cols)