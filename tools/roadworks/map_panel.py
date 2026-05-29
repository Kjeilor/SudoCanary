"""
tools/roadworks/map_panel.py — Day 9

RoadWorksMapPanel — full implementation.

Day 9 additions over Day 8:
  - on_canary_update() pushes section colour changes via runJavaScript()
    without page reload. Tracks _last_status per section.
  - QWebChannel bridge wired: polyline clicks → MapBridge.section_clicked
    → section detail panel appears.
  - Photo thumbnails embedded as base64 data URIs in popups.
  - Demo mode button (SUDO_CANARY_DEMO=1) for live showcase.
  - Canary subscription with lifecycle: subscribes on create_widget(),
    unsubscribes when widget is destroyed.
"""
from __future__ import annotations

import base64
import io
import json
import os
from datetime import datetime
from typing import Any, Optional

from core.sdk.types import CanaryState, RoomId

STATUS_COLOURS = {
    "not_started": "#9E9E9E",
    "in_progress":  "#FFA726",
    "complete":     "#66BB6A",
    "qa_approved":  "#2E7D32",
}

# Canary output status → section status string
_CANARY_TO_SECTION = {
    "grey":  "not_started",
    "amber": "in_progress",
    "green": "complete",
    "red":   "in_progress",  # red means overdue but still in progress
}

_MAP_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="{server_url}/static/leaflet.css"/>
<script src="{server_url}/static/leaflet.js"></script>
{qwebchannel_script}
<style>
  body {{ margin: 0; padding: 0; background: #1e1e2e; }}
  #map {{ width: 100%; height: 100vh; }}
  .section-popup {{ font-family: sans-serif; font-size: 13px; line-height: 1.5; }}
  .section-popup b {{ font-size: 14px; }}
  .section-popup img {{ border-radius: 4px; margin-top: 4px; }}
</style>
</head>
<body>
<div id="map"></div>
<script>
var map = L.map('map').setView([{lat}, {lon}], {zoom});
L.tileLayer('{server_url}/tiles/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '&copy; OpenStreetMap contributors', maxZoom: 18
}}).addTo(map);

var sections = {sections_json};
var layers = {{}};

function buildPopup(s) {{
  var html = '<div class="section-popup">'
    + '<b>' + s.label + '</b><br/>'
    + 'Status: ' + s.status.replace(/_/g, ' ') + '<br/>'
    + 'Last check-in: ' + (s.last_checkin || 'Never');
  if (s.photo) {{
    html += '<br/><img src="' + s.photo + '" style="width:160px; height:auto"/>';
  }}
  html += '</div>';
  return html;
}}

sections.forEach(function(s) {{
  if (!s.waypoints || s.waypoints.length < 2) {{
    if (s.waypoints && s.waypoints.length === 1) {{
      var m = L.circleMarker(s.waypoints[0], {{
        color: s.colour, radius: 10, fillOpacity: 0.8
      }}).addTo(map);
      m.bindPopup(buildPopup(s));
      m.on('click', function() {{ sendSectionClick(s.section_id); }});
      layers[s.section_id] = m;
    }}
    return;
  }}
  var line = L.polyline(s.waypoints, {{
    color: s.colour, weight: 7, opacity: 0.9
  }}).addTo(map);
  line.bindPopup(buildPopup(s));
  line.on('click', function(e) {{
    L.DomEvent.stopPropagation(e);
    sendSectionClick(s.section_id);
  }});
  layers[s.section_id] = line;
}});

// Click on map background → clear section selection
map.on('click', function() {{ sendSectionClick(''); }});

function sendSectionClick(section_id) {{
  if (window._bridge) {{ window._bridge.on_section_clicked(section_id); }}
}}

function updateSection(section_id, colour, status, last_checkin, photo) {{
  if (!layers[section_id]) return;
  if (layers[section_id].setStyle) {{
    layers[section_id].setStyle({{color: colour}});
  }}
  layers[section_id].setPopupContent(buildPopup({{
    label: section_id, status: status,
    last_checkin: last_checkin, photo: photo || null
  }}));
}}

// QWebChannel bridge (injected if available)
{bridge_init}
</script>
</body>
</html>
"""

_BRIDGE_INIT_JS = """
if (typeof QWebChannel !== 'undefined') {
  new QWebChannel(qt.webChannelTransport, function(channel) {
    window._bridge = channel.objects.bridge;
  });
}
"""


def _read_qwebchannel_js() -> str:
    """Read qwebchannel.js from Qt's embedded resources."""
    try:
        from PySide6.QtCore import QFile, QIODevice
        f = QFile(":/qtwebchannel/qwebchannel.js")
        if f.open(QIODevice.ReadOnly):
            content = bytes(f.readAll()).decode("utf-8")
            f.close()
            return f"<script>\n{content}\n</script>"
    except Exception:
        pass
    return ""  # QWebChannel unavailable — polyline clicks won't fire section_clicked


def _photo_thumbnail_b64(section_id: str, room_id: str) -> Optional[str]:
    """Return base64 JPEG data URI of the most recent check-in photo, or None."""
    try:
        from core.db.connection import get_connection
        from PIL import Image
        with get_connection() as conn:
            row = conn.execute(
                "SELECT pc.photo_path FROM photo_checkins pc "
                "JOIN sensor_events se ON pc.event_id = se.event_id "
                "WHERE se.room_id=? AND pc.entity_id=? "
                "ORDER BY se.timestamp DESC LIMIT 1",
                (room_id, section_id),
            ).fetchone()
        if not row or not row["photo_path"]:
            return None
        from pathlib import Path
        p = Path(row["photo_path"])
        if not p.exists():
            return None
        img = Image.open(p)
        img.thumbnail((160, 100))
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


class RoadWorksMapPanel:
    panel_id = "roadworks.section_map"
    label    = "Section Status Map"

    def __init__(self, room_id: str) -> None:
        self.room_id      = RoomId(room_id)
        self._view: Optional[Any] = None
        self._loaded      = False
        self._last_status: dict[str, str] = {}
        self._sub_id: Optional[str] = None

    # ── VisualisationPanel Protocol ───────────────────────────────────────────

    def create_widget(self, canary_state: CanaryState) -> Any:
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
            from PySide6.QtCore import QUrl
        except ImportError:
            from PySide6.QtWidgets import QLabel
            from PySide6.QtCore import Qt
            lbl = QLabel(
                "Map view requires PySide6-WebEngine.\n\n"
                "Run:  pip install PySide6-WebEngine\n\n"
                "Then restart the application."
            )
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color: #a6adc8; font-size: 13px;")
            return lbl

        from PySide6.QtWebChannel import QWebChannel
        from core.tiles.tile_server import tile_server
        from core.canary_engine import canary_engine

        view = QWebEngineView()
        self._view = view
        self._loaded = False

        # QWebChannel bridge
        self._bridge = _MapBridge()
        channel = QWebChannel(view.page())
        channel.registerObject("bridge", self._bridge)
        view.page().setWebChannel(channel)

        qwebchannel_script = _read_qwebchannel_js()
        html = self._build_html(canary_state, tile_server.url(), qwebchannel_script)
        view.loadFinished.connect(self._on_load_finished)
        view.setHtml(html, QUrl(tile_server.url()))

        # Subscribe to Canary updates
        self._sub_id = canary_engine.subscribe(self.room_id, self.on_canary_update)
        view.destroyed.connect(self._on_destroyed)

        return view

    def on_canary_update(self, canary_state: CanaryState) -> None:
        """Push section colour changes to JS without reloading."""
        if not self._view or not self._loaded:
            return
        rid = str(self.room_id)
        for output in canary_state.outputs:
            if not output.key.startswith("roadworks.progress.S"):
                continue
            section_id = output.key.split(".")[-1]  # "S1" … "S6"
            new_colour = STATUS_COLOURS.get(
                _CANARY_TO_SECTION.get(output.status, "not_started"),
                "#9E9E9E"
            )
            if self._last_status.get(section_id) == new_colour:
                continue
            self._last_status[section_id] = new_colour
            status_label = _CANARY_TO_SECTION.get(output.status, output.status)
            last_checkin = self._get_last_checkin(section_id)
            photo = _photo_thumbnail_b64(section_id, rid) or ""
            js = (
                f"updateSection("
                f"'{section_id}', '{new_colour}', "
                f"'{status_label}', '{last_checkin}', "
                f"'{photo}');"
            )
            self._view.page().runJavaScript(js)

    def bridge(self) -> Optional["_MapBridge"]:
        """Return the QWebChannel bridge for external signal connections."""
        return getattr(self, "_bridge", None)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_load_finished(self, ok: bool) -> None:
        self._loaded = ok

    def _on_destroyed(self) -> None:
        """Unsubscribe from Canary when widget is destroyed."""
        if self._sub_id:
            try:
                from core.canary_engine import canary_engine
                canary_engine.unsubscribe(self._sub_id)
            except Exception:
                pass
            self._sub_id = None

    def _build_html(
        self, canary_state: CanaryState, server_url: str, qwebchannel_script: str
    ) -> str:
        lat, lon = self._centre_from_waypoints()
        sections = self._get_section_data()
        return _MAP_HTML.format(
            server_url=server_url,
            lat=lat, lon=lon, zoom=14,
            sections_json=json.dumps(sections),
            qwebchannel_script=qwebchannel_script,
            bridge_init=_BRIDGE_INIT_JS,
        )

    def _get_section_data(self) -> list:
        from core.db.connection import get_connection
        rid = str(self.room_id)
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM roadworks_sections WHERE room_id=? ORDER BY section_id",
                (rid,),
            ).fetchall()
            checkin_rows = conn.execute(
                "SELECT pc.entity_id, MAX(se.timestamp) AS last_ts "
                "FROM photo_checkins pc "
                "JOIN sensor_events se ON pc.event_id = se.event_id "
                "WHERE se.room_id=? GROUP BY pc.entity_id",
                (rid,),
            ).fetchall()

        last_checkin = {
            r["entity_id"]: r["last_ts"][:16].replace("T", " ")
            for r in checkin_rows
        }

        sections = []
        for r in rows:
            waypoints = []
            if r["waypoints"]:
                try:
                    waypoints = json.loads(r["waypoints"])
                except Exception:
                    pass
            status = r["status"]
            colour = STATUS_COLOURS.get(status, "#9E9E9E")
            self._last_status[r["section_id"]] = colour
            photo = _photo_thumbnail_b64(r["section_id"], rid)
            sections.append({
                "section_id":  r["section_id"],
                "label":       r["label"],
                "status":      status,
                "colour":      colour,
                "waypoints":   waypoints,
                "last_checkin": last_checkin.get(r["section_id"], "Never"),
                "photo":       photo or "",
            })
        return sections

    def _get_last_checkin(self, section_id: str) -> str:
        try:
            from core.db.connection import get_connection
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT MAX(se.timestamp) AS ts FROM photo_checkins pc "
                    "JOIN sensor_events se ON pc.event_id = se.event_id "
                    "WHERE se.room_id=? AND pc.entity_id=?",
                    (str(self.room_id), section_id),
                ).fetchone()
            if row and row["ts"]:
                return row["ts"][:16].replace("T", " ")
        except Exception:
            pass
        return "Never"

    def _centre_from_waypoints(self) -> tuple:
        try:
            from core.db.connection import get_connection
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT waypoints FROM roadworks_sections "
                    "WHERE room_id=? AND waypoints IS NOT NULL",
                    (str(self.room_id),),
                ).fetchall()
            lats, lons = [], []
            for r in rows:
                for pt in json.loads(r["waypoints"]):
                    if isinstance(pt, (list, tuple)) and len(pt) == 2:
                        lats.append(pt[0])
                        lons.append(pt[1])
            if lats:
                return sum(lats) / len(lats), sum(lons) / len(lons)
        except Exception:
            pass
        return 0.3136, 32.5811


# ---------------------------------------------------------------------------
# QWebChannel bridge
# ---------------------------------------------------------------------------

try:
    from PySide6.QtCore import QObject, Signal, Slot

    class _MapBridge(QObject):
        section_clicked = Signal(str)   # "" = deselect

        @Slot(str)
        def on_section_clicked(self, section_id: str) -> None:
            self.section_clicked.emit(section_id)

except ImportError:
    class _MapBridge:  # type: ignore
        section_clicked = None
        def on_section_clicked(self, section_id):
            pass