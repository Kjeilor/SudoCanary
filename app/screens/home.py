"""
Staging area — shown after MFA, before entering a room.
Displays accessible rooms as cards: name, role, canary status, task summary.
"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.models.user import User
from core.room_impl import RoomAPIImpl
from core.task_impl import task_service

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
        self.setFixedSize(220, 140)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QFrame { background-color: #181825; border-radius: 10px; }"
            "QFrame:hover { background-color: #1e1e2e; }"
        )
        self._room_id = room["room_id"]
        self._room_name = room["name"]
        self._build_ui(room, actor)

    def _build_ui(self, room: dict, actor: User) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        # Room name
        name = QLabel(room["name"])
        name.setFont(QFont("", 12, QFont.Bold))
        name.setWordWrap(True)

        # Role badge
        from core.auth.rbac import get_room_role
        from core.sdk.types import RoomId
        role = get_room_role(actor, RoomId(room["room_id"]))
        role_label = QLabel(role.value.replace("_", " ").title() if role else "")
        role_label.setStyleSheet("color: #a6adc8;")

        # Canary status — grey until engine (Day 6)
        canary_row = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {_STATUS_COLOUR['grey']};")
        status_text = QLabel("Pending")
        status_text.setStyleSheet("color: #6c7086;")
        canary_row.addWidget(dot)
        canary_row.addWidget(status_text)
        canary_row.addStretch()

        # Task summary
        try:
            from core.sdk.types import RoomId
            counts = task_service.count_by_status(actor, RoomId(room["room_id"]))
            task_text = f"{counts['active']} active"
            if counts["overdue"]:
                task_text += f"  ·  {counts['overdue']} overdue"
            task_label = QLabel(task_text)
            if counts["overdue"]:
                task_label.setStyleSheet("color: #f9e2af;")
            else:
                task_label.setStyleSheet("color: #a6adc8;")
        except Exception:
            task_label = QLabel("No tasks")
            task_label.setStyleSheet("color: #6c7086;")

        layout.addWidget(name)
        layout.addWidget(role_label)
        layout.addStretch()
        layout.addLayout(canary_row)
        layout.addWidget(task_label)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._room_id, self._room_name)
        super().mousePressEvent(event)


class StagingArea(QWidget):
    room_selected    = Signal(str, str)  # room_id, room_name
    settings_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 32, 40, 32)

        header = QLabel("Your Rooms")
        header.setFont(QFont("", 18, QFont.Bold))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._grid_widget = QWidget()
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(16)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setWidget(self._grid_widget)

        self._empty_label = QLabel("You have no rooms yet. Ask your administrator to add you to a room.")
        self._empty_label.setStyleSheet("color: #6c7086;")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.hide()

        layout.addWidget(header)
        layout.addSpacing(16)
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
        for i, room in enumerate(rooms):
            card = _RoomCard(room, actor)
            card.clicked.connect(self.room_selected)
            self._grid.addWidget(card, i // 3, i % 3)