"""
tools/roadworks/section_detail.py

Section detail panel — sits to the right of the map in a QSplitter.
Always visible; shows empty state when no section is selected.
Appears/updates when MapBridge.section_clicked fires.
Clears when section_clicked emits "" (map background clicked).

Data sources:
  - roadworks_sections: status, length_km
  - roadworks_km_progress: cumulative km paved per section
  - photo_checkins: most recent check-in timestamp and photo thumbnail
  - roadworks_materials: total acquired vs consumed, worst divergence
  - tasks: open/overdue count filtered by tags.section_id
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from core.db.connection import get_connection
from core.models.user import User
from core.sdk.types import RoomId


_COLOUR = {
    "not_started": "#9E9E9E",
    "in_progress":  "#FFA726",
    "complete":     "#66BB6A",
    "qa_approved":  "#2E7D32",
}


def _load_section_data(section_id: str, room_id: str) -> dict:
    """Load all data needed for the detail panel from the database."""
    from datetime import datetime

    rid = room_id
    data: dict = {
        "section_id": section_id,
        "label": section_id,
        "status": "not_started",
        "length_km": 2.0,
        "km_paved": 0.0,
        "last_checkin": "Never",
        "checkin_actor": "",
        "checkin_hours_ago": None,
        "gps_lat": None,
        "gps_lon": None,
        "photo_path": None,
        "materials": [],
        "worst_divergence": None,
        "tasks_open": 0,
        "tasks_overdue": 0,
    }

    with get_connection() as conn:
        # Section basics
        row = conn.execute(
            "SELECT * FROM roadworks_sections WHERE section_id=? AND room_id=?",
            (section_id, rid),
        ).fetchone()
        if row:
            data["label"]     = row["label"]
            data["status"]    = row["status"]
            data["length_km"] = row["length_km"]

        # KM progress
        km_row = conn.execute(
            "SELECT COALESCE(MAX(cumulative_km), 0) AS cum "
            "FROM roadworks_km_progress WHERE section_id=? AND room_id=?",
            (section_id, rid),
        ).fetchone()
        if km_row:
            data["km_paved"] = km_row["cum"]

        # Last check-in
        ci_row = conn.execute(
            "SELECT se.timestamp, se.user_id, se.payload, "
            "       u.display_name "
            "FROM photo_checkins pc "
            "JOIN sensor_events se ON pc.event_id = se.event_id "
            "LEFT JOIN users u ON se.user_id = u.user_id "
            "WHERE se.room_id=? AND pc.entity_id=? "
            "ORDER BY se.timestamp DESC LIMIT 1",
            (rid, section_id),
        ).fetchone()
        if ci_row:
            import json as _json
            data["last_checkin"]  = ci_row["timestamp"][:16].replace("T", " ")
            data["checkin_actor"] = ci_row["display_name"] or ci_row["user_id"]
            ts = datetime.fromisoformat(ci_row["timestamp"])
            hours = (datetime.utcnow() - ts).total_seconds() / 3600
            data["checkin_hours_ago"] = round(hours, 1)
            try:
                payload = _json.loads(ci_row["payload"] or "{}")
                data["gps_lat"] = payload.get("gps_lat")
                data["gps_lon"] = payload.get("gps_lon")
                data["photo_path"] = payload.get("photo_path")
            except Exception:
                pass

        # Materials
        mat_rows = conn.execute(
            "SELECT material, SUM(quantity_acquired) AS acq, "
            "       SUM(quantity_consumed) AS con, unit "
            "FROM roadworks_materials WHERE section_id=? AND room_id=? "
            "GROUP BY material, unit",
            (section_id, rid),
        ).fetchall()
        materials = []
        worst_div = None
        for r in mat_rows:
            acq = r["acq"] or 0
            con = r["con"] or 0
            div = round((con - acq) / acq * 100, 1) if acq > 0 else 0
            materials.append({
                "material": r["material"],
                "acquired": acq,
                "consumed": con,
                "unit": r["unit"],
                "divergence_pct": div,
            })
            if worst_div is None or abs(div) > abs(worst_div):
                worst_div = div
        data["materials"] = materials
        data["worst_divergence"] = worst_div

        # Tasks tagged for this section
        import json as _json2
        task_rows = conn.execute(
            "SELECT status, due_at FROM tasks WHERE room_id=? "
            "AND status NOT IN ('complete','cancelled') AND tags IS NOT NULL",
            (rid,),
        ).fetchall()
        now = datetime.utcnow().isoformat()
        open_count = 0
        overdue_count = 0
        for t in task_rows:
            try:
                tags = _json2.loads(t["tags"] or "{}")
                if tags.get("section_id") != section_id:
                    continue
                open_count += 1
                if t["due_at"] and t["due_at"] < now:
                    overdue_count += 1
            except Exception:
                pass
        data["tasks_open"]    = open_count
        data["tasks_overdue"] = overdue_count

    return data


class SectionDetailPanel(QScrollArea):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedWidth(300)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(12)
        self.setWidget(self._container)

        self._show_empty()

    # ── Public API ────────────────────────────────────────────────────────────

    def show_section(self, section_id: str, room_id: str, actor: User) -> None:
        if not section_id:
            self._show_empty()
            return
        data = _load_section_data(section_id, room_id)
        self._render(data)

    def clear(self) -> None:
        self._show_empty()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _show_empty(self) -> None:
        self._clear_layout()
        lbl = QLabel("Click a section on the map\nto view details.")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color: #6c7086; font-size: 13px;")
        self._layout.addStretch()
        self._layout.addWidget(lbl, alignment=Qt.AlignCenter)
        self._layout.addStretch()

    def _render(self, d: dict) -> None:
        self._clear_layout()

        # ── Header ────────────────────────────────────────────────────────────
        colour = _COLOUR.get(d["status"], "#9E9E9E")
        status_label = d["status"].replace("_", " ").title()
        header = QLabel(f"<span style='color:{colour}'>●</span>  {d['label']} — {status_label}")
        header.setFont(QFont("", 13, QFont.Bold))
        header.setTextFormat(Qt.RichText)
        header.setWordWrap(True)
        self._layout.addWidget(header)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("color: #313244;")
        self._layout.addWidget(divider)

        # ── Progress ──────────────────────────────────────────────────────────
        self._layout.addWidget(self._section_group("Progress",
            self._progress_widget(d)))

        # ── Last check-in ──────────────────────────────────────────────────────
        self._layout.addWidget(self._section_group("Last Check-in",
            self._checkin_widget(d)))

        # ── Materials ─────────────────────────────────────────────────────────
        if d["materials"]:
            self._layout.addWidget(self._section_group("Materials",
                self._materials_widget(d)))

        # ── QA Status ──────────────────────────────────────────────────────────
        self._layout.addWidget(self._section_group("QA Status",
            self._qa_widget(d)))

        # ── Tasks ────────────────────────────────────────────────────────────
        self._layout.addWidget(self._section_group("Tasks",
            self._tasks_widget(d)))

        self._layout.addStretch()

    def _section_group(self, title: str, widget: QWidget) -> QGroupBox:
        group = QGroupBox(title)
        gl = QVBoxLayout(group)
        gl.setContentsMargins(8, 8, 8, 8)
        gl.addWidget(widget)
        return group

    def _progress_widget(self, d: dict) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        km = d["km_paved"]
        total = d["length_km"]
        pct = (km / total * 100) if total > 0 else 0

        lbl = QLabel(f"{km:.2f} / {total:.1f} km  ({pct:.0f}%)")
        lbl.setStyleSheet("color: #cdd6f4;")

        # Progress bar using label with background
        filled = int(pct / 5)  # 0–20 blocks
        bar_filled = "█" * filled
        bar_empty  = "░" * (20 - filled)
        bar = QLabel(bar_filled + bar_empty)
        bar.setStyleSheet("color: #89b4fa; font-family: monospace;")

        layout.addWidget(lbl)
        layout.addWidget(bar)
        return w

    def _checkin_widget(self, d: dict) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        # Photo thumbnail
        if d.get("photo_path"):
            try:
                from pathlib import Path
                from PIL import Image
                p = Path(d["photo_path"])
                if p.exists():
                    img = Image.open(p)
                    img.thumbnail((200, 120))
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    import io as _io
                    buf = _io.BytesIO()
                    img.save(buf, format="JPEG")
                    pixmap = QPixmap()
                    pixmap.loadFromData(buf.getvalue())
                    photo_lbl = QLabel()
                    photo_lbl.setPixmap(pixmap)
                    layout.addWidget(photo_lbl)
            except Exception:
                pass

        if d["last_checkin"] == "Never":
            layout.addWidget(QLabel("No check-in recorded.", styleSheet="color:#6c7086;"))
        else:
            layout.addWidget(QLabel(f"📷  {d['checkin_actor']}", styleSheet="color:#cdd6f4;"))
            hours = d.get("checkin_hours_ago")
            if hours is not None:
                ago = f"{hours:.0f} hours ago" if hours >= 1 else "< 1 hour ago"
                layout.addWidget(QLabel(ago, styleSheet="color:#a6adc8;"))
            layout.addWidget(QLabel(d["last_checkin"], styleSheet="color:#6c7086; font-size:11px;"))
            if d.get("gps_lat") is not None:
                gps = f"GPS: {d['gps_lat']:.4f}°N, {d['gps_lon']:.4f}°E"
                layout.addWidget(QLabel(gps, styleSheet="color:#6c7086; font-size:11px;"))
        return w

    def _materials_widget(self, d: dict) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        for m in d["materials"]:
            div = m["divergence_pct"]
            colour = "#f38ba8" if div > 30 else "#f9e2af" if div > 15 else "#a6adc8"
            text = (
                f"{m['material'].title()}: "
                f"{m['acquired']:.0f} / {m['consumed']:.0f} {m['unit']}"
            )
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #cdd6f4;")
            layout.addWidget(lbl)
            if abs(div) > 0.5:
                warn = QLabel(f"  {'⚠' if div > 15 else '↑'} {div:+.1f}% divergence")
                warn.setStyleSheet(f"color: {colour};")
                layout.addWidget(warn)
        return w

    def _qa_widget(self, d: dict) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        status = d["status"]
        if status == "qa_approved":
            lbl = QLabel("● QA Approved")
            lbl.setStyleSheet("color: #a6e3a1;")
        elif status == "complete":
            lbl = QLabel("● Complete — pending QA")
            lbl.setStyleSheet("color: #89b4fa;")
        else:
            lbl = QLabel("● Not approved")
            lbl.setStyleSheet("color: #6c7086;")
        layout.addWidget(lbl)
        return w

    def _tasks_widget(self, d: dict) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        open_c   = d["tasks_open"]
        overdue  = d["tasks_overdue"]
        if open_c == 0:
            lbl = QLabel("No open tasks")
            lbl.setStyleSheet("color: #6c7086;")
            layout.addWidget(lbl)
        else:
            text = f"{open_c} open"
            colour = "#cdd6f4"
            if overdue:
                text += f"  ·  {overdue} overdue"
                colour = "#f9e2af"
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {colour};")
            layout.addWidget(lbl)
        return w