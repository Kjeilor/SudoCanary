"""Settings page — appearance, accessibility. Persisted to user_preferences table."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from core.db.connection import get_connection
from core.models.user import User


def _load_prefs(user_id: str) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row:
        return dict(row)
    return {
        "theme": "dark", "font_size": "M",
        "colour_blind_mode": "none", "high_contrast": 0,
    }


def _save_prefs(user_id: str, prefs: dict) -> None:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_preferences
               (user_id, theme, font_size, colour_blind_mode, high_contrast, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
               theme=excluded.theme, font_size=excluded.font_size,
               colour_blind_mode=excluded.colour_blind_mode,
               high_contrast=excluded.high_contrast,
               updated_at=excluded.updated_at""",
            (
                user_id, prefs["theme"], prefs["font_size"],
                prefs["colour_blind_mode"], prefs["high_contrast"], now,
            ),
        )


class SettingsScreen(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._user_id: str | None = None
        self._build_ui()

    def load_user(self, user: User) -> None:
        self._user_id = user.user_id
        prefs = _load_prefs(user.user_id)
        self._apply_prefs(prefs)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 40, 60, 40)
        layout.setSpacing(24)

        back_btn = QPushButton("← Back to Rooms")
        back_btn.setFlat(True)
        back_btn.setStyleSheet("color: #89b4fa;")
        back_btn.clicked.connect(self.back_requested)

        title = QLabel("Settings")
        title.setFont(QFont("", 20, QFont.Bold))

        # ── Appearance ────────────────────────────────────────────────
        appearance = QGroupBox("Appearance")
        app_layout = QVBoxLayout(appearance)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self._theme_grp = QButtonGroup(self)
        for label, val in [("Light", "light"), ("Dark", "dark"), ("System", "system")]:
            rb = QRadioButton(label)
            rb.setProperty("theme_val", val)
            self._theme_grp.addButton(rb)
            theme_row.addWidget(rb)
        theme_row.addStretch()

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Font size:"))
        self._size_grp = QButtonGroup(self)
        for sz in ["S", "M", "L", "XL"]:
            rb = QRadioButton(sz)
            rb.setProperty("size_val", sz)
            self._size_grp.addButton(rb)
            size_row.addWidget(rb)
        size_row.addStretch()

        app_layout.addLayout(theme_row)
        app_layout.addLayout(size_row)

        # ── Accessibility ─────────────────────────────────────────────
        accessibility = QGroupBox("Accessibility")
        acc_layout = QVBoxLayout(accessibility)

        cb_row = QHBoxLayout()
        cb_row.addWidget(QLabel("Colour blind mode:"))
        self._cb_grp = QButtonGroup(self)
        for label, val in [
            ("None", "none"), ("Deuteranopia", "deuteranopia"),
            ("Protanopia", "protanopia"), ("Tritanopia", "tritanopia"),
            ("Monochromacy", "monochromacy"),
        ]:
            rb = QRadioButton(label)
            rb.setProperty("cb_val", val)
            self._cb_grp.addButton(rb)
            cb_row.addWidget(rb)
        cb_row.addStretch()

        self._high_contrast = QCheckBox("High contrast")

        acc_layout.addLayout(cb_row)
        acc_layout.addWidget(self._high_contrast)

        # ── Coming soon ───────────────────────────────────────────────
        coming = QGroupBox("Coming soon")
        coming_layout = QVBoxLayout(coming)
        coming_layout.addWidget(QLabel("Screen reader  ·  Keyboard navigation  ·  Motor accessibility"))
        coming.setEnabled(False)

        # ── Save ──────────────────────────────────────────────────────
        save_btn = QPushButton("Save Settings")
        save_btn.setFixedHeight(40)
        save_btn.clicked.connect(self._save)

        layout.addWidget(back_btn)
        layout.addWidget(title)
        layout.addWidget(appearance)
        layout.addWidget(accessibility)
        layout.addWidget(coming)
        layout.addStretch()
        layout.addWidget(save_btn)

    def _apply_prefs(self, prefs: dict) -> None:
        for btn in self._theme_grp.buttons():
            if btn.property("theme_val") == prefs.get("theme", "dark"):
                btn.setChecked(True)
        for btn in self._size_grp.buttons():
            if btn.property("size_val") == prefs.get("font_size", "M"):
                btn.setChecked(True)
        for btn in self._cb_grp.buttons():
            if btn.property("cb_val") == prefs.get("colour_blind_mode", "none"):
                btn.setChecked(True)
        self._high_contrast.setChecked(bool(prefs.get("high_contrast", 0)))

    def _save(self) -> None:
        if not self._user_id:
            return
        theme_btn = self._theme_grp.checkedButton()
        size_btn = self._size_grp.checkedButton()
        cb_btn = self._cb_grp.checkedButton()
        prefs = {
            "theme":             theme_btn.property("theme_val") if theme_btn else "dark",
            "font_size":         size_btn.property("size_val") if size_btn else "M",
            "colour_blind_mode": cb_btn.property("cb_val") if cb_btn else "none",
            "high_contrast":     1 if self._high_contrast.isChecked() else 0,
        }
        _save_prefs(self._user_id, prefs)
        self.back_requested.emit()