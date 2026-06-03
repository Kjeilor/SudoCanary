"""
app/widgets/kpi_card.py

Reusable dashboard KPI card. Large stat number, label, optional badge.
Uses class properties for QSS targeting.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout


class KPICard(QFrame):
    """
    A dashboard KPI card.

    Usage:
        card = KPICard("Open Tasks", "12", "3 overdue", "stat-badge-red")
    """

    def __init__(
        self,
        label: str,
        value: str = "—",
        badge_text: str = "",
        badge_class: str = "stat-badge-green",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setMinimumHeight(100)
        self._build_ui(label, value, badge_text, badge_class)

    def _build_ui(
        self,
        label: str,
        value: str,
        badge_text: str,
        badge_class: str,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        lbl = QLabel(label)
        lbl.setProperty("class", "subheading")

        val_row = QHBoxLayout()
        self._val_lbl = QLabel(value)
        self._val_lbl.setProperty("class", "stat-number")

        val_row.addWidget(self._val_lbl)
        if badge_text:
            self._badge = QLabel(badge_text)
            self._badge.setProperty("class", badge_class)
            val_row.addWidget(self._badge, alignment=Qt.AlignBottom)
        else:
            self._badge = None
        val_row.addStretch()

        layout.addWidget(lbl)
        layout.addLayout(val_row)

    def update_value(
        self,
        value: str,
        badge_text: str = "",
        badge_class: str = "stat-badge-green",
    ) -> None:
        self._val_lbl.setText(value)
        if self._badge and badge_text:
            self._badge.setText(badge_text)
            self._badge.setProperty("class", badge_class)
            self._badge.style().unpolish(self._badge)
            self._badge.style().polish(self._badge)