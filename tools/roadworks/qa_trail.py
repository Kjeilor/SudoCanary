"""
tools/roadworks/qa_trail.py

QA trail view — shows the complete QA sign-off history for the project.
Reads sensor_events where sensor_id = 'roadworks.qa_signoff'.
Supersessions shown as indented rows below the section they supersede.
Accessible from the section detail panel and RoadWorks toolbar.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.db.connection import get_connection


class QATrailView(QWidget):
    def __init__(self, room_id: str, parent=None) -> None:
        super().__init__(parent)
        self._room_id = room_id
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("QA Trail — Road Reconstruction Project")
        title.setFont(QFont("", 14, QFont.Bold))

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFlat(True)
        refresh_btn.setStyleSheet("color: #89b4fa;")
        refresh_btn.clicked.connect(self.refresh)

        hdr = QHBoxLayout()
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(refresh_btn)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Section", "Inspector", "Date", "Status", "Notes"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.verticalHeader().hide()
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)

        self._supersession_label = QLabel("")
        self._supersession_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        self._supersession_label.setWordWrap(True)

        layout.addLayout(hdr)
        layout.addWidget(self._table, stretch=1)
        layout.addWidget(self._supersession_label)

    def refresh(self) -> None:
        self._table.setRowCount(0)
        rows = self._load_data()
        supersessions = []

        # Group events by section — latest approval per section + supersessions
        by_section: dict[str, list] = {}
        for r in rows:
            sid = r["section_id"]
            if sid not in by_section:
                by_section[sid] = []
            by_section[sid].append(r)

        # Get all sections (for pending display)
        with get_connection() as conn:
            section_rows = conn.execute(
                "SELECT section_id, label FROM roadworks_sections "
                "WHERE room_id=? ORDER BY section_id",
                (self._room_id,),
            ).fetchall()

        all_sections = {r["section_id"]: r["label"] for r in section_rows}
        if not all_sections:
            # Fallback if no sections configured
            all_sections = {f"S{i}": f"Section {i}" for i in range(1, 7)}

        for sid in sorted(all_sections):
            events = by_section.get(sid, [])
            if not events:
                # Pending
                self._add_row(sid, "—", "—", "⏳ Pending", "—", False)
                continue

            # Sort by timestamp
            events.sort(key=lambda e: e["timestamp"])
            for i, ev in enumerate(events):
                approved    = ev.get("approved", False)
                status_icon = "✅ Approved" if approved else "❌ Rejected"
                is_supersession = ev.get("supersession_reason") and i > 0
                date_str    = ev["timestamp"][:10] if ev["timestamp"] else "—"
                notes       = ev.get("notes") or "—"

                if is_supersession:
                    supersessions.append({
                        "section": sid,
                        "date":    date_str,
                        "reason":  ev["supersession_reason"],
                        "inspector": ev.get("inspector_name", "—"),
                    })
                    label = f"  ↳ Supersession"
                else:
                    label = sid

                self._add_row(
                    label,
                    ev.get("inspector_name", "—"),
                    date_str,
                    status_icon,
                    notes,
                    is_supersession,
                )

        # Supersession summary below table
        if supersessions:
            lines = ["Supersessions:"]
            for s in supersessions:
                lines.append(
                    f"  {s['section']}  Superseded {s['date']} by {s['inspector']}"
                    f"  —  \"{s['reason']}\""
                )
            self._supersession_label.setText("\n".join(lines))
        else:
            self._supersession_label.setText("")

    def _add_row(
        self,
        section: str,
        inspector: str,
        date: str,
        status: str,
        notes: str,
        is_sub: bool,
    ) -> None:
        r = self._table.rowCount()
        self._table.insertRow(r)
        for col, val in enumerate([section, inspector, date, status, notes]):
            item = QTableWidgetItem(val)
            if is_sub:
                item.setForeground(Qt.gray)
            self._table.setItem(r, col, item)

    def _load_data(self) -> list:
        """Load all QA sign-off sensor events for this room."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT se.timestamp, se.user_id, se.payload, u.display_name "
                "FROM sensor_events se "
                "LEFT JOIN users u ON se.user_id = u.user_id "
                "WHERE se.room_id=? AND se.sensor_id='roadworks.qa_signoff' "
                "ORDER BY se.timestamp",
                (self._room_id,),
            ).fetchall()

        results = []
        for r in rows:
            try:
                payload = json.loads(r["payload"] or "{}")
            except Exception:
                payload = {}
            results.append({
                "timestamp":          r["timestamp"],
                "display_name":       r["display_name"] or r["user_id"],
                "section_id":         payload.get("section_id", "?"),
                "approved":           payload.get("approved", False),
                "inspector_name":     payload.get("inspector_name", r["display_name"] or "—"),
                "inspection_date":    payload.get("inspection_date", ""),
                "notes":              payload.get("notes", ""),
                "supersession_reason": payload.get("supersession_reason", ""),
            })
        return results