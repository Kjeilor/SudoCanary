"""
tools/roadworks/segment_mapper.py — Day 9

Two-tab setup widget.
Tab 1 — Section Setup: labels, lengths (unchanged from Day 8)
Tab 2 — Waypoints: click-on-map via QWebChannel (Day 9 upgrade)
         Each click fires bridge.on_map_click → waypoint_added signal
         → point added to the waypoints table + redrawn on map.
         Falls back to QTableWidget entry if QWebChannel unavailable.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core.db.connection import get_connection
from core.sdk.types import RoomId

QR_BASE = Path("data/qr")

_WAYPOINT_MAP_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="{server_url}/static/leaflet.css"/>
<script src="{server_url}/static/leaflet.js"></script>
{qwebchannel_script}
<style>
  body {{ margin: 0; }}
  #map {{ width: 100%; height: 100vh; }}
  #hint {{ position: absolute; top: 10px; left: 50px; z-index: 1000;
           background: rgba(30,30,46,0.85); color:#cdd6f4;
           padding: 6px 12px; border-radius: 6px; font-size: 13px;
           font-family: sans-serif; }}
</style>
</head>
<body>
<div id="map"></div>
<div id="hint">Click on the map to add waypoints for the selected section</div>
<script>
var map = L.map('map').setView([{lat}, {lon}], {zoom});
L.tileLayer('{server_url}/tiles/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '&copy; OpenStreetMap contributors', maxZoom: 18
}}).addTo(map);

var markers   = [];
var polyline  = null;
var _bridge   = null;

function redraw() {{
  if (polyline) {{ polyline.remove(); polyline = null; }}
  if (markers.length < 2) return;
  var latlngs = markers.map(function(m) {{ return m.getLatLng(); }});
  polyline = L.polyline(latlngs, {{color:'#FFA726', weight:5}}).addTo(map);
}}

function clearAll() {{
  markers.forEach(function(m) {{ m.remove(); }});
  markers = [];
  if (polyline) {{ polyline.remove(); polyline = null; }}
}}

function undoLast() {{
  if (!markers.length) return;
  markers[markers.length-1].remove();
  markers.pop();
  redraw();
}}

function loadWaypoints(pts) {{
  clearAll();
  pts.forEach(function(pt) {{
    var m = L.circleMarker([pt[0], pt[1]],
      {{radius:6, color:'#89b4fa', fillOpacity:0.9}}).addTo(map);
    markers.push(m);
  }});
  redraw();
  if (markers.length) {{
    map.fitBounds(L.featureGroup(markers).getBounds(), {{padding:[30,30]}});
  }}
}}

// QWebChannel setup
{bridge_init}

// Allow direct JS calls if bridge isn't ready yet
function addMarker(lat, lon) {{
  var m = L.circleMarker([lat, lon],
    {{radius:6, color:'#89b4fa', fillOpacity:0.9}}).addTo(map);
  markers.push(m);
  redraw();
}}

map.on('click', function(e) {{
  addMarker(e.latlng.lat, e.latlng.lng);
  if (_bridge) {{ _bridge.on_map_click(e.latlng.lat, e.latlng.lng); }}
}});
</script>
</body>
</html>
"""

_BRIDGE_INIT = """
if (typeof QWebChannel !== 'undefined') {
  new QWebChannel(qt.webChannelTransport, function(channel) {
    _bridge = channel.objects.bridge;
  });
}
"""


def _read_qwebchannel_js() -> str:
    try:
        from PySide6.QtCore import QFile, QIODevice
        f = QFile(":/qtwebchannel/qwebchannel.js")
        if f.open(QIODevice.ReadOnly):
            content = bytes(f.readAll()).decode("utf-8")
            f.close()
            return f"<script>\n{content}\n</script>"
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# MapBridge — shared between segment mapper and status map
# ---------------------------------------------------------------------------

try:
    from PySide6.QtCore import QObject, Slot

    class MapBridge(QObject):
        from PySide6.QtCore import Signal
        waypoint_added  = Signal(float, float)
        section_clicked = Signal(str)

        @Slot(float, float)
        def on_map_click(self, lat: float, lon: float) -> None:
            self.waypoint_added.emit(lat, lon)

        @Slot(str)
        def on_section_clicked(self, section_id: str) -> None:
            self.section_clicked.emit(section_id)

except ImportError:
    class MapBridge:  # type: ignore
        waypoint_added  = None
        section_clicked = None
        def on_map_click(self, lat, lon): pass
        def on_section_clicked(self, sid): pass


# ---------------------------------------------------------------------------
# Tab 1 — Section Setup
# ---------------------------------------------------------------------------

class _SectionSetupTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        note = QLabel(
            "Define your road sections. Each section gets its own QR code for field check-ins."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #a6adc8;")

        config = QGroupBox("Project Configuration")
        form = QFormLayout(config)
        self._project_name = QLineEdit()
        self._project_name.setPlaceholderText("e.g. Kampala Northern Bypass Phase 2")
        self._total_length = QDoubleSpinBox()
        self._total_length.setRange(0.1, 1000.0)
        self._total_length.setValue(12.0)
        self._total_length.setSuffix(" km")
        self._total_length.setDecimals(1)
        self._num_sections = QSpinBox()
        self._num_sections.setRange(2, 12)
        self._num_sections.setValue(6)
        gen_btn = QPushButton("Auto-generate sections")
        gen_btn.setFixedHeight(32)
        gen_btn.clicked.connect(self.auto_generate)
        form.addRow("Project name *", self._project_name)
        form.addRow("Total road length", self._total_length)
        form.addRow("Number of sections", self._num_sections)
        form.addRow("", gen_btn)

        sections_group = QGroupBox("Sections")
        sl = QVBoxLayout(sections_group)
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Section ID", "Label", "Length (km)"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.verticalHeader().hide()
        self._table.setMaximumHeight(220)
        sl.addWidget(self._table)

        layout.addWidget(note)
        layout.addWidget(config)
        layout.addWidget(sections_group)
        layout.addStretch()
        self.auto_generate()

    def auto_generate(self) -> None:
        n = self._num_sections.value()
        total = self._total_length.value()
        per = round(total / n, 2)
        self._table.setRowCount(0)
        for i in range(1, n + 1):
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem(f"S{i}"))
            self._table.setItem(r, 1, QTableWidgetItem(f"Section {i}"))
            self._table.setItem(r, 2, QTableWidgetItem(str(per)))

    def project_name(self) -> str:
        return self._project_name.text().strip()

    def collect_sections(self) -> List[dict]:
        sections = []
        for r in range(self._table.rowCount()):
            sid   = (self._table.item(r, 0) or QTableWidgetItem("")).text().strip()
            label = (self._table.item(r, 1) or QTableWidgetItem("")).text().strip()
            try:
                length = float((self._table.item(r, 2) or QTableWidgetItem("2")).text())
            except ValueError:
                length = 2.0
            if sid:
                sections.append({"id": sid, "label": label or sid, "length": length})
        return sections


# ---------------------------------------------------------------------------
# Tab 2 — Waypoints (QWebChannel click-on-map)
# ---------------------------------------------------------------------------

class _WaypointTab(QWidget):
    def __init__(self, room_id: str, parent=None) -> None:
        super().__init__(parent)
        self._room_id   = room_id
        self._sections: List[dict] = []
        self._view      = None
        self._bridge: Optional[MapBridge] = None
        self._waypoints: List[List[float]] = []  # current section's in-memory list
        self._build_ui()

    def set_sections(self, sections: List[dict]) -> None:
        self._sections = sections
        self._section_combo.clear()
        for s in sections:
            self._section_combo.addItem(f"{s['id']} — {s['label']}", s["id"])
        self._load_section_waypoints()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # ── Left controls ─────────────────────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(280)
        ll = QVBoxLayout(left)
        ll.setSpacing(8)

        ll.addWidget(QLabel("Section:"))
        self._section_combo = QComboBox()
        self._section_combo.currentIndexChanged.connect(self._on_section_changed)
        ll.addWidget(self._section_combo)

        ll.addSpacing(6)
        self._count_lbl = QLabel("0 points")
        self._count_lbl.setStyleSheet("color: #a6adc8;")
        ll.addWidget(self._count_lbl)

        # Waypoint table (read-only display)
        self._wp_table = QTableWidget(0, 2)
        self._wp_table.setHorizontalHeaderLabels(["Latitude", "Longitude"])
        self._wp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._wp_table.verticalHeader().hide()
        self._wp_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._wp_table.setMaximumHeight(260)
        ll.addWidget(self._wp_table)

        undo_btn = QPushButton("↩  Undo last point")
        undo_btn.setFixedHeight(30)
        undo_btn.clicked.connect(self._undo_last)
        clear_btn = QPushButton("✕  Clear section")
        clear_btn.setFixedHeight(30)
        clear_btn.clicked.connect(self._clear_section)
        preview_btn = QPushButton("👁  Preview route")
        preview_btn.setFixedHeight(30)
        preview_btn.clicked.connect(self._preview_route)
        save_btn = QPushButton("💾  Save waypoints")
        save_btn.setFixedHeight(34)
        save_btn.clicked.connect(self._save_waypoints)

        ll.addWidget(undo_btn)
        ll.addWidget(clear_btn)
        ll.addWidget(preview_btn)
        ll.addSpacing(8)
        ll.addWidget(save_btn)
        ll.addStretch()

        # ── Map view ──────────────────────────────────────────────────────────
        self._map_container = QWidget()
        self._map_layout = QVBoxLayout(self._map_container)
        self._map_layout.setContentsMargins(0, 0, 0, 0)

        placeholder = QLabel("Loading map…")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #6c7086;")
        self._map_layout.addWidget(placeholder)

        layout.addWidget(left)
        layout.addWidget(self._map_container, stretch=1)

    def showEvent(self, event) -> None:
        """Initialise the map on first show."""
        super().showEvent(event)
        if self._view is None:
            self._init_map()

    def _init_map(self) -> None:
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtWebChannel import QWebChannel
            from PySide6.QtCore import QUrl
            from core.tiles.tile_server import tile_server
        except ImportError:
            fallback = QLabel(
                "Click-on-map requires PySide6-WebEngine.\n"
                "Enter waypoints manually below."
            )
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setStyleSheet("color: #a6adc8;")
            while self._map_layout.count():
                item = self._map_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._map_layout.addWidget(fallback)
            return

        view = QWebEngineView()
        self._view = view
        self._bridge = MapBridge()
        self._bridge.waypoint_added.connect(self._on_waypoint_added)

        channel = QWebChannel(view.page())
        channel.registerObject("bridge", self._bridge)
        view.page().setWebChannel(channel)

        qwebchannel_script = _read_qwebchannel_js()
        html = _WAYPOINT_MAP_HTML.format(
            server_url=tile_server.url(),
            lat=0.3136, lon=32.5811, zoom=13,
            qwebchannel_script=qwebchannel_script,
            bridge_init=_BRIDGE_INIT,
        )
        view.setHtml(html, QUrl(tile_server.url()))

        while self._map_layout.count():
            item = self._map_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._map_layout.addWidget(view)

    def _on_section_changed(self, idx: int) -> None:
        self._load_section_waypoints()

    def _load_section_waypoints(self) -> None:
        section_id = self._section_combo.currentData()
        if not section_id:
            return
        self._waypoints = []
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT waypoints FROM roadworks_sections WHERE section_id=? AND room_id=?",
                    (section_id, self._room_id),
                ).fetchone()
            if row and row["waypoints"]:
                self._waypoints = json.loads(row["waypoints"])
        except Exception:
            pass
        self._sync_table()
        self._push_to_map(self._waypoints)

    def _on_waypoint_added(self, lat: float, lon: float) -> None:
        self._waypoints.append([lat, lon])
        self._sync_table()

    def _sync_table(self) -> None:
        self._wp_table.setRowCount(len(self._waypoints))
        for i, (lat, lon) in enumerate(self._waypoints):
            self._wp_table.setItem(i, 0, QTableWidgetItem(f"{lat:.6f}"))
            self._wp_table.setItem(i, 1, QTableWidgetItem(f"{lon:.6f}"))
        self._count_lbl.setText(f"{len(self._waypoints)} point(s)")

    def _push_to_map(self, points: List[list]) -> None:
        if not self._view:
            return
        js = f"loadWaypoints({json.dumps(points)});"
        self._view.page().runJavaScript(js)

    def _undo_last(self) -> None:
        if self._waypoints:
            self._waypoints.pop()
            self._sync_table()
            if self._view:
                self._view.page().runJavaScript("undoLast();")

    def _clear_section(self) -> None:
        self._waypoints = []
        self._sync_table()
        if self._view:
            self._view.page().runJavaScript("clearAll();")

    def _preview_route(self) -> None:
        self._push_to_map(self._waypoints)

    def _save_waypoints(self) -> None:
        section_id = self._section_combo.currentData()
        if not section_id:
            return
        with get_connection() as conn:
            conn.execute(
                "UPDATE roadworks_sections SET waypoints=?, updated_at=? "
                "WHERE section_id=? AND room_id=?",
                (json.dumps(self._waypoints), datetime.utcnow().isoformat(),
                 section_id, self._room_id),
            )
        QMessageBox.information(
            self, "Saved",
            f"{len(self._waypoints)} waypoints saved for {section_id}."
        )


# ---------------------------------------------------------------------------
# SegmentMapperWidget
# ---------------------------------------------------------------------------

class SegmentMapperWidget(QWidget):
    setup_complete = Signal()

    def __init__(self, room_id: str, parent=None) -> None:
        super().__init__(parent)
        self._room_id = room_id
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Road Project Setup")
        header.setFont(QFont("", 16, QFont.Bold))
        header.setContentsMargins(16, 16, 16, 8)

        self._tabs = QTabWidget()
        self._setup_tab = _SectionSetupTab()
        self._waypoint_tab = _WaypointTab(self._room_id)
        self._tabs.addTab(self._setup_tab, "1 · Section Setup")
        self._tabs.addTab(self._waypoint_tab, "2 · Waypoints")
        self._tabs.currentChanged.connect(self._on_tab_changed)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(16, 8, 16, 16)
        save_btn = QPushButton("Save Sections & Generate QR Codes")
        save_btn.setFixedHeight(40)
        save_btn.clicked.connect(self._save_all)
        done_btn = QPushButton("Done →")
        done_btn.setFixedHeight(40)
        done_btn.clicked.connect(self.setup_complete)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(done_btn)

        layout.addWidget(header)
        layout.addWidget(self._tabs, stretch=1)
        layout.addLayout(btn_row)

    def _on_tab_changed(self, idx: int) -> None:
        if idx == 1:
            sections = self._setup_tab.collect_sections()
            if sections:
                self._waypoint_tab.set_sections(sections)

    def _save_all(self) -> None:
        if not self._setup_tab.project_name():
            QMessageBox.warning(self, "Required", "Project name is required.")
            return
        sections = self._setup_tab.collect_sections()
        if not sections:
            QMessageBox.warning(self, "Required", "Add at least one section.")
            return
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            for s in sections:
                conn.execute(
                    "INSERT OR REPLACE INTO roadworks_sections "
                    "(section_id, room_id, label, length_km, status, updated_at) "
                    "VALUES (?,?,?,?,'not_started',?)",
                    (s["id"], self._room_id, s["label"], s["length"], now),
                )
        self._generate_qrs(sections)
        QMessageBox.information(
            self, "Saved",
            f"{len(sections)} sections saved.\n"
            "QR codes written to data/qr/{room_id}/\n\n"
            "Use the Waypoints tab to map each section's route."
        )

    def _generate_qrs(self, sections: List[dict]) -> None:
        try:
            from core.sensors.qr_checkin import QRCheckInSensorImpl
            from core.sdk.types import SensorId
            dest_dir = QR_BASE / self._room_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            sensor = QRCheckInSensorImpl(
                SensorId("roadworks.photo_checkin"),
                RoomId(self._room_id), "Site Photo Check-in", {},
            )
            for s in sections:
                png = sensor.generate_qr(s["id"])
                (dest_dir / f"{s['id']}.png").write_bytes(png)
        except Exception as exc:
            print(f"QR generation warning: {exc}")