"""
app/screens/workflows.py

Workflows tab — functional scaffold (Day 4).

Reads workflow_instances from the database.
STALLED instances highlighted amber.
COMPLETE instances in a separate section.
No step advancement UI — that comes Day 6.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core.db.connection import get_connection
from core.models.user import User
from core.sdk.types import RoomId

_STATUS_COLOUR = {
    "active":    "#cdd6f4",
    "stalled":   "#f9e2af",
    "complete":  "#a6e3a1",
    "cancelled": "#6c7086",
}

_STATUS_LABEL = {
    "active":    "Active",
    "stalled":   "Stalled",
    "complete":  "Complete",
    "cancelled": "Cancelled",
}


def _load_instances(room_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT wi.*, u.display_name as initiator_name "
            "FROM workflow_instances wi "
            "LEFT JOIN users u ON wi.initiated_by = u.user_id "
            "WHERE wi.room_id = ? "
            "ORDER BY wi.started_at DESC",
            (room_id,),
        ).fetchall()
    return [dict(r) for r in rows]


class WorkflowsView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: Optional[User] = None
        self._room_id: Optional[RoomId] = None
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        toolbar = QHBoxLayout()
        header = QLabel("Workflows")
        header.setFont(QFont("", 16, QFont.Bold))
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFixedHeight(34)
        refresh_btn.clicked.connect(self._refresh)
        toolbar.addWidget(header)
        toolbar.addStretch()
        toolbar.addWidget(refresh_btn)

        self._empty_label = QLabel(
            "No workflows configured.\n"
            "An Admin can add workflow templates."
        )
        self._empty_label.setStyleSheet("color: #6c7086;")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.hide()

        # Active / stalled group
        self._active_group = QGroupBox("Active & Stalled")
        active_layout = QVBoxLayout(self._active_group)
        self._active_table = self._make_table()
        active_layout.addWidget(self._active_table)

        # Completed group
        self._complete_group = QGroupBox("Completed")
        complete_layout = QVBoxLayout(self._complete_group)
        self._complete_table = self._make_table()
        complete_layout.addWidget(self._complete_table)

        layout.addLayout(toolbar)
        layout.addWidget(self._empty_label)
        layout.addWidget(self._active_group)
        layout.addWidget(self._complete_group)
        layout.addStretch()

    def _make_table(self) -> QTableWidget:
        t = QTableWidget(0, 5)
        t.setHorizontalHeaderLabels(
            ["Title", "Current Step", "Status", "Started by", "Started at"]
        )
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.verticalHeader().hide()
        t.setAlternatingRowColors(True)
        return t

    def _refresh(self) -> None:
        if not self._room_id:
            return

        instances = _load_instances(str(self._room_id))

        active = [i for i in instances if i["status"] in ("active", "stalled")]
        complete = [i for i in instances if i["status"] in ("complete", "cancelled")]

        if not instances:
            self._empty_label.show()
            self._active_group.hide()
            self._complete_group.hide()
            self.status_message.emit("No workflows")
            return

        self._empty_label.hide()
        self._active_group.setVisible(bool(active))
        self._complete_group.setVisible(bool(complete))

        self._fill_table(self._active_table, active)
        self._fill_table(self._complete_table, complete)

        n_stalled = sum(1 for i in active if i["status"] == "stalled")
        msg = f"{len(instances)} workflow(s)"
        if n_stalled:
            msg += f"  ·  {n_stalled} stalled"
        self.status_message.emit(msg)

    def _fill_table(self, table: QTableWidget, rows: list[dict]) -> None:
        table.setRowCount(0)
        for inst in rows:
            r = table.rowCount()
            table.insertRow(r)
            started = inst["started_at"][:16].replace("T", " ")
            cells = [
                inst["title"],
                inst["current_step_label"],
                _STATUS_LABEL.get(inst["status"], inst["status"]),
                inst.get("initiator_name") or inst["initiated_by"],
                started,
            ]
            colour = QColor(_STATUS_COLOUR.get(inst["status"], "#cdd6f4"))
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                if inst["status"] == "stalled":
                    item.setForeground(colour)
                elif inst["status"] == "complete":
                    item.setForeground(colour)
                table.setItem(r, col, item)