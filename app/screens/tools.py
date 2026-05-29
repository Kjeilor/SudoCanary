"""
app/screens/tools.py — Day 9

Tools tab. Day 9 additions:
  - Map panel + section detail in QSplitter (70/30 split)
  - Section detail wired to MapBridge.section_clicked
  - Demo mode button (SUDO_CANARY_DEMO=1)
  - Tile cache verification banner on first open
"""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from core.auth.rbac import is_admin
from core.db.connection import get_connection
from core.models.user import User
from core.sdk.types import RoomId

DEMO_MODE = os.environ.get("SUDO_CANARY_DEMO", "0") == "1"


class _SimpleVizRegistry:
    def __init__(self):
        self._panels = {}
    def register_panel(self, panel) -> None:
        self._panels[(panel.panel_id, str(panel.room_id))] = panel
    def unregister_panel(self, panel_id, room_id) -> None:
        self._panels.pop((panel_id, str(room_id)), None)
    def get_panel(self, panel_id, room_id):
        return self._panels.get((panel_id, str(room_id)))
    def list_panels(self, room_id):
        return [k[0] for k in self._panels if k[1] == str(room_id)]


_viz_registry = _SimpleVizRegistry()

_STATE_EMPTY  = 0
_STATE_PERMS  = 1
_STATE_MAPPER = 2
_STATE_CARD   = 3
_STATE_PANEL  = 4


class _PermissionsDialog(QWidget):
    approved  = Signal()
    cancelled = Signal()

    def __init__(self, tool, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        title = QLabel(f"Install {tool.tool_name} v{tool.tool_version}")
        title.setFont(QFont("", 16, QFont.Bold))
        desc = QLabel(tool.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a6adc8;")
        decl = tool.get_permissions()
        perm_group = QFrame()
        perm_group.setStyleSheet("QFrame { background: #181825; border-radius: 8px; }")
        pgl = QVBoxLayout(perm_group)
        pgl.setContentsMargins(16, 12, 16, 12)
        pgl.addWidget(QLabel("<b>This tool requires permission to:</b>", textFormat=Qt.RichText))
        for action in decl.required_actions:
            lbl = QLabel(f"  • {action.replace('_', ' ').title()}")
            lbl.setStyleSheet("color: #cdd6f4;")
            pgl.addWidget(lbl)
        just = QLabel(decl.justification)
        just.setWordWrap(True)
        just.setStyleSheet("color: #6c7086; font-style: italic;")
        btn_row = QHBoxLayout()
        approve_btn = QPushButton("Approve & Install")
        approve_btn.setFixedHeight(38)
        approve_btn.clicked.connect(self.approved)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFlat(True)
        cancel_btn.clicked.connect(self.cancelled)
        btn_row.addWidget(approve_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addSpacing(8)
        layout.addWidget(perm_group)
        layout.addWidget(just)
        layout.addStretch()
        layout.addLayout(btn_row)


class _ToolCard(QFrame):
    open_clicked      = Signal()
    uninstall_clicked = Signal()

    def __init__(self, tool_row: dict, is_admin_user: bool, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("QFrame { background: #181825; border-radius: 10px; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        name = QLabel("🗺  RoadWorks  v1.0.0")
        name.setFont(QFont("", 14, QFont.Bold))
        desc = QLabel("Infrastructure project management for road reconstruction.")
        desc.setStyleSheet("color: #a6adc8;")
        installed_at = (tool_row.get("installed_at") or "")[:10]
        meta = QLabel(f"Installed  ·  {installed_at}")
        meta.setStyleSheet("color: #6c7086; font-size: 12px;")
        btn_row = QHBoxLayout()
        open_btn = QPushButton("Open Map")
        open_btn.setFixedHeight(34)
        open_btn.clicked.connect(self.open_clicked)
        btn_row.addWidget(open_btn)
        if is_admin_user:
            uninst_btn = QPushButton("Uninstall")
            uninst_btn.setFixedHeight(34)
            uninst_btn.setStyleSheet("color: #f38ba8;")
            uninst_btn.clicked.connect(self.uninstall_clicked)
            btn_row.addWidget(uninst_btn)
        btn_row.addStretch()
        layout.addWidget(name)
        layout.addWidget(desc)
        layout.addWidget(meta)
        layout.addSpacing(8)
        layout.addLayout(btn_row)


class ToolsView(QWidget):
    status_message  = Signal(str)
    tools_installed = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: Optional[User] = None
        self._room_id: Optional[RoomId] = None
        self._panel = None   # RoadWorksMapPanel instance
        self._detail_panel = None
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        self._panel = None
        self._refresh()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        header = QLabel("Tools")
        header.setFont(QFont("", 16, QFont.Bold))
        outer.addWidget(header)
        outer.addSpacing(8)

        self._stack = QStackedWidget()

        # 0 empty
        self._empty = QWidget()
        el = QVBoxLayout(self._empty)
        el.setAlignment(Qt.AlignCenter)
        el.addWidget(QLabel("No tools are installed in this room.",
                             styleSheet="color:#6c7086;", alignment=Qt.AlignCenter))
        self._install_btn = QPushButton("Install a Tool")
        self._install_btn.setFixedWidth(160)
        self._install_btn.setFixedHeight(36)
        self._install_btn.clicked.connect(self._show_permissions)
        el.addSpacing(12)
        el.addWidget(self._install_btn, alignment=Qt.AlignCenter)

        # 1 permissions
        self._perms_container = QWidget()
        self._perms_layout = QVBoxLayout(self._perms_container)

        # 2 mapper
        self._mapper_container = QWidget()
        self._mapper_layout = QVBoxLayout(self._mapper_container)
        self._mapper_layout.setContentsMargins(0, 0, 0, 0)

        # 3 tool card
        self._card_container = QWidget()
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setAlignment(Qt.AlignTop)

        # 4 map panel with detail splitter
        self._panel_container = QWidget()
        self._panel_outer_layout = QVBoxLayout(self._panel_container)
        self._panel_outer_layout.setContentsMargins(0, 0, 0, 0)

        for w in (self._empty, self._perms_container, self._mapper_container,
                  self._card_container, self._panel_container):
            self._stack.addWidget(w)

        outer.addWidget(self._stack, stretch=1)

    def _refresh(self) -> None:
        with get_connection() as conn:
            tool_row = conn.execute(
                "SELECT * FROM installed_tools WHERE room_id=? AND tool_id='roadworks'",
                (str(self._room_id),),
            ).fetchone()

        is_admin_user = is_admin(self._actor)
        self._install_btn.setVisible(is_admin_user)

        if not tool_row:
            self.tools_installed.emit(False)
            self._stack.setCurrentIndex(_STATE_EMPTY)
            self.status_message.emit("No tools installed")
            return

        self.tools_installed.emit(True)

        with get_connection() as conn:
            sections = conn.execute(
                "SELECT COUNT(*) FROM roadworks_sections WHERE room_id=?",
                (str(self._room_id),),
            ).fetchone()[0]

        if sections == 0:
            self._show_segment_mapper()
        else:
            self._show_tool_card(dict(tool_row), is_admin_user)

    def _show_permissions(self) -> None:
        from tools.roadworks import RoadWorksTool
        while self._perms_layout.count():
            item = self._perms_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        tool = RoadWorksTool()
        dlg = _PermissionsDialog(tool)
        dlg.approved.connect(lambda: self._do_install(tool))
        dlg.cancelled.connect(lambda: self._stack.setCurrentIndex(_STATE_EMPTY))
        self._perms_layout.addWidget(dlg)
        self._stack.setCurrentIndex(_STATE_PERMS)

    def _do_install(self, tool) -> None:
        from core.room_impl import RoomAPIImpl
        try:
            room_api = RoomAPIImpl(self._actor)
            tool.install([self._room_id], room_api, None, _viz_registry, None)
            self.status_message.emit("RoadWorks installed")
            top = self.window()
            if hasattr(top, "_banner_bar"):
                top._banner_bar.show_banner("RoadWorks installed successfully.", kind="success")
            self._show_segment_mapper()
            self.tools_installed.emit(True)
        except Exception as exc:
            QMessageBox.critical(self, "Install failed", str(exc))
            self._stack.setCurrentIndex(_STATE_EMPTY)

    def _show_segment_mapper(self) -> None:
        from tools.roadworks.segment_mapper import SegmentMapperWidget
        while self._mapper_layout.count():
            item = self._mapper_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        mapper = SegmentMapperWidget(str(self._room_id))
        mapper.setup_complete.connect(self._on_mapper_complete)
        self._mapper_layout.addWidget(mapper)
        self._stack.setCurrentIndex(_STATE_MAPPER)
        self.status_message.emit("Configure road sections")

    def _on_mapper_complete(self) -> None:
        with get_connection() as conn:
            tool_row = conn.execute(
                "SELECT * FROM installed_tools WHERE room_id=? AND tool_id='roadworks'",
                (str(self._room_id),),
            ).fetchone()
        self._show_tool_card(dict(tool_row) if tool_row else {}, is_admin(self._actor))
        top = self.window()
        if hasattr(top, "_banner_bar"):
            top._banner_bar.show_banner("Sections saved. QR codes generated.", kind="success")

    def _show_tool_card(self, tool_row: dict, is_admin_user: bool) -> None:
        while self._card_layout.count():
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        card = _ToolCard(tool_row, is_admin_user)
        card.open_clicked.connect(self._open_map_panel)
        card.uninstall_clicked.connect(self._uninstall)
        self._card_layout.addWidget(card)
        self._card_layout.addStretch()
        self._stack.setCurrentIndex(_STATE_CARD)
        self.status_message.emit("RoadWorks")
        self._check_tile_cache()

    def _check_tile_cache(self) -> None:
        """Show amber banner if tile cache is below 80%."""
        try:
            from core.tiles.tile_server import tile_server
            result = tile_server.verify_cache(
                zoom_levels=list(range(10, 17)),
                bounds={"west": 32.4, "south": 0.1, "east": 32.8, "north": 0.5},
            )
            if result["total"] > 0 and result["pct"] < 80:
                top = self.window()
                if hasattr(top, "_banner_bar"):
                    top._banner_bar.show_banner(
                        f"Map tile cache is incomplete ({result['pct']}% coverage). "
                        "Run: python3 tools/_tile_downloader.py",
                        kind="warning",
                    )
        except Exception:
            pass

    def _open_map_panel(self) -> None:
        """Build map + detail panel in a QSplitter and show."""
        while self._panel_outer_layout.count():
            item = self._panel_outer_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        from tools.roadworks.map_panel import RoadWorksMapPanel
        from tools.roadworks.section_detail import SectionDetailPanel
        from core.canary_engine import canary_engine

        # Top toolbar
        toolbar = QHBoxLayout()
        back_btn = QPushButton("← Back")
        back_btn.setFlat(True)
        back_btn.setStyleSheet("color: #89b4fa;")
        back_btn.clicked.connect(lambda: self._stack.setCurrentIndex(_STATE_CARD))
        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setFlat(True)
        refresh_btn.setStyleSheet("color: #89b4fa;")
        refresh_btn.clicked.connect(self._open_map_panel)
        toolbar.addWidget(back_btn)
        toolbar.addStretch()

        if DEMO_MODE:
            demo_btn = QPushButton("▶  Demo: Submit S3 Progress")
            demo_btn.setFixedHeight(30)
            demo_btn.setStyleSheet("background: #313244; color: #f9e2af;")
            demo_btn.clicked.connect(self._run_demo_submission)
            toolbar.addWidget(demo_btn)

        toolbar.addWidget(refresh_btn)

        toolbar_widget = QWidget()
        toolbar_widget.setFixedHeight(38)
        toolbar_widget.setLayout(toolbar)

        # Map + detail splitter
        splitter = QSplitter(Qt.Horizontal)

        self._panel = RoadWorksMapPanel(str(self._room_id))
        state = canary_engine.get_latest_state(self._room_id)
        if state is None:
            state = canary_engine.compute(self._room_id)

        map_widget = self._panel.create_widget(state)

        self._detail_panel = SectionDetailPanel()

        # Wire section click bridge
        bridge = self._panel.bridge()
        if bridge:
            bridge.section_clicked.connect(self._on_section_clicked)

        splitter.addWidget(map_widget)
        splitter.addWidget(self._detail_panel)
        splitter.setSizes([700, 300])

        self._panel_outer_layout.addWidget(toolbar_widget)
        self._panel_outer_layout.addWidget(splitter, stretch=1)
        self._stack.setCurrentIndex(_STATE_PANEL)
        self.status_message.emit("Section Status Map")

    def _on_section_clicked(self, section_id: str) -> None:
        if not self._detail_panel:
            return
        if not section_id:
            self._detail_panel.clear()
        else:
            self._detail_panel.show_section(
                section_id, str(self._room_id), self._actor
            )

    def _run_demo_submission(self) -> None:
        """Demo mode: submit a pre-configured KM progress form for S3."""
        from datetime import date
        from core.sensors.form_sensor import sensor_service
        from tools.roadworks.sensors import km_progress_callback

        try:
            sensors = sensor_service.load_for_room(str(self._room_id))
            km_sensor = next(
                (s for s in sensors if str(s.sensor_id) == "roadworks.km_progress"),
                None,
            )
            if not km_sensor:
                QMessageBox.warning(self, "Demo", "KM Progress sensor not found.")
                return

            km_sensor._callback = km_progress_callback
            payload = {
                "section_id": "S3",
                "km_paved": 0.8,
                "date": date.today().isoformat(),
                "notes": "Demo submission — showcasing live map update",
            }
            km_sensor.submit(self._actor, payload)
            top = self.window()
            if hasattr(top, "_banner_bar"):
                top._banner_bar.show_banner(
                    "Demo: S3 KM progress submitted — map updating…", kind="success"
                )
        except Exception as exc:
            QMessageBox.critical(self, "Demo failed", str(exc))

    def _uninstall(self) -> None:
        confirm = QMessageBox.question(
            self, "Uninstall RoadWorks",
            "Uninstall RoadWorks? Sensor data and audit records are preserved.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        from tools.roadworks import RoadWorksTool
        try:
            RoadWorksTool().uninstall([self._room_id])
            self.tools_installed.emit(False)
            self._stack.setCurrentIndex(_STATE_EMPTY)
            self.status_message.emit("RoadWorks uninstalled")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))