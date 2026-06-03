"""
app/widgets/sidebar.py — Day 12

Narrow icon-only sidebar (56px). Icons centred, tooltips on hover.
Active item: #29AB87 left border. Class properties set for QSS targeting.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

_NAV_ITEMS = [
    ("dashboard",    "⊞",  "Dashboard"),
    ("tasks",        "✓",  "Tasks"),
    ("workflows",    "⟳",  "Workflows"),
    ("sensors",      "⊡",  "Sensors"),
    ("documents",    "⎗",  "Documents"),
    ("directory",    "👥", "Directory"),
    ("tools",        "🔧", "Tools"),
    ("reports",      "↗",  "Reports"),
]


class RoomSidebar(QWidget):
    nav_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setProperty("class", "sidebar")
        self.setFixedWidth(56)
        self._buttons: dict[str, QPushButton] = {}
        self._active_key: str = ""
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)

        # Nav buttons
        for key, icon, label in _NAV_ITEMS:
            btn = self._make_btn(icon, label)
            btn.clicked.connect(lambda _=False, k=key: self.nav_requested.emit(k))
            self._buttons[key] = btn
            layout.addWidget(btn)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("color: #444444;")
        layout.addWidget(div)

        # Training (locked)
        training_btn = self._make_btn("🎓", "Training (coming soon)")
        training_btn.setEnabled(False)
        self._buttons["training"] = training_btn
        layout.addWidget(training_btn)

        layout.addStretch()

        # Bottom: connectivity indicator
        self._conn_lbl = QLabel("🟢")
        self._conn_lbl.setAlignment(Qt.AlignCenter)
        self._conn_lbl.setFixedHeight(36)
        self._conn_lbl.setToolTip("Connected")
        layout.addWidget(self._conn_lbl)

        # Tools hidden by default
        self._buttons["tools"].hide()

    def _make_btn(self, icon: str, tooltip: str) -> QPushButton:
        btn = QPushButton(icon)
        btn.setProperty("class", "sidebar-item")
        btn.setProperty("active", "false")
        btn.setFixedWidth(56)
        btn.setFixedHeight(48)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    # ── Public API ────────────────────────────────────────────────────────────

    def set_room(self, room_name: str, role, member_count: int) -> None:
        """Room info is now shown in the top bar breadcrumb — nothing to do here."""
        pass

    def set_active(self, key: str) -> None:
        if self._active_key and self._active_key in self._buttons:
            btn = self._buttons[self._active_key]
            btn.setProperty("active", "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self._active_key = key
        if key in self._buttons:
            btn = self._buttons[key]
            btn.setProperty("active", "true")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_tools_visible(self, visible: bool) -> None:
        if "tools" in self._buttons:
            self._buttons["tools"].setVisible(visible)

    def set_connectivity(self, online: bool) -> None:
        self._conn_lbl.setText("🟢" if online else "🔴")
        self._conn_lbl.setToolTip("Connected" if online else "Offline")