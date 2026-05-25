"""
Room-level left sidebar. Role-aware — Sensors hidden for Viewer.
Training always visible but locked. Tools hidden if no tool installed.
Emits nav_requested(str) with the view key when an item is clicked.
"""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QLabel, QPushButton, QVBoxLayout, QWidget, QFrame, QSizePolicy,
)
from PySide6.QtGui import QFont

from core.models.user import RoomRole

_NAV_ITEMS = [
    ("dashboard",      "📊  Dashboard"),
    ("tasks",          "✓   Tasks"),
    ("workflows",      "⟳   Workflows"),
    ("sensors",        "⊡   Sensors"),
    ("documents",      "⎗   Documents"),
    ("directory",      "👥  Directory"),
    ("tools",          "🔧  Tools"),
    ("reports",        "↗   Reports"),
    ("activity_feed",  "📋  Activity Feed"),
]

_VIEWER_HIDDEN = {"sensors", "tools"}


class RoomSidebar(QWidget):
    nav_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(220)
        self._buttons: dict[str, QPushButton] = {}
        self._current = "dashboard"
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Room header
        self._room_label = QLabel("Room")
        self._room_label.setFont(QFont("", 13, QFont.Bold))
        self._room_label.setContentsMargins(16, 16, 16, 4)
        self._room_label.setWordWrap(True)

        self._role_label = QLabel("")
        self._role_label.setContentsMargins(16, 0, 16, 12)
        self._role_label.setStyleSheet("color: #a6adc8;")

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #313244;")

        layout.addWidget(self._room_label)
        layout.addWidget(self._role_label)
        layout.addWidget(divider)

        # Nav items
        for key, label in _NAV_ITEMS:
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setFixedHeight(40)
            btn.setCheckable(True)
            btn.setStyleSheet(self._btn_style(False))
            btn.clicked.connect(lambda checked, k=key: self._on_nav(k))
            btn.setContentsMargins(16, 0, 0, 0)
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # Divider before locked items
        div2 = QFrame()
        div2.setFrameShape(QFrame.HLine)
        div2.setStyleSheet("color: #313244;")
        layout.addWidget(div2)

        # Training — always visible, locked
        training_btn = QPushButton("🎓  Training")
        training_btn.setFlat(True)
        training_btn.setFixedHeight(40)
        training_btn.setEnabled(False)
        training_btn.setToolTip("Coming soon")
        training_btn.setStyleSheet("color: #585b70; padding-left: 16px;")
        layout.addWidget(training_btn)

        # Member count + status
        self._members_label = QLabel("👥  — members")
        self._members_label.setContentsMargins(16, 8, 16, 8)
        self._members_label.setStyleSheet("color: #a6adc8;")
        layout.addWidget(self._members_label)

    def set_room(self, name: str, role: RoomRole, member_count: int) -> None:
        self._room_label.setText(name)
        self._role_label.setText(f"[{role.value.replace('_', ' ').title()}]")
        self._members_label.setText(f"👥  {member_count} member{'s' if member_count != 1 else ''}")

        # Hide items the role cannot access
        for key, btn in self._buttons.items():
            if role == RoomRole.VIEWER and key in _VIEWER_HIDDEN:
                btn.hide()
            else:
                btn.show()

        # Tools hidden by default — shown when a Tool is installed
        self._buttons["tools"].hide()

    def set_active(self, key: str) -> None:
        for k, btn in self._buttons.items():
            active = k == key
            btn.setChecked(active)
            btn.setStyleSheet(self._btn_style(active))
        self._current = key

    def _on_nav(self, key: str) -> None:
        self.set_active(key)
        self.nav_requested.emit(key)

    @staticmethod
    def _btn_style(active: bool) -> str:
        if active:
            return (
                "QPushButton { background-color: #313244; color: #cdd6f4; "
                "text-align: left; padding-left: 16px; border: none; }"
            )
        return (
            "QPushButton { background-color: transparent; color: #a6adc8; "
            "text-align: left; padding-left: 16px; border: none; }"
            "QPushButton:hover { background-color: #1e1e2e; color: #cdd6f4; }"
        )