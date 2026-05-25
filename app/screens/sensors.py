"""
app/screens/sensors.py — Day 5

Left panel: sensor list (form sensors and QR check-in sensors).
Right panel: dispatches based on sensor type.
  - FormSensorImpl → FormRenderer + submission history
  - QRCheckInSensorImpl → entity table with Scan/QR buttons

Sensor history hardened:
  - Human-readable messages via audit.py format_event()
  - Photo thumbnails for check-in entries
  - Failed submissions (audit_log success=0) shown with red indicator

Manual sensor builder: Admin-only, Custom Sensor, replaced Day 8.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QVBoxLayout, QWidget,
)

from core.auth.rbac import can_manage_room
from core.models.user import RoomRole, User
from core.sdk.types import RoomId
from core.sensors.form_sensor import FormSensorImpl, sensor_service
from core.sensors.qr_checkin import QRCheckInSensorImpl
from app.widgets.form_renderer import FormRenderer
from app.widgets.qr_display import QRDisplayWidget

# ---------------------------------------------------------------------------
# Sensor factory — loads form or QR sensors based on x-sensor-type in schema
# ---------------------------------------------------------------------------

def _load_sensors_for_room(room_id: str) -> List:
    """Load sensors, returning FormSensorImpl or QRCheckInSensorImpl."""
    from core.db.connection import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM sensors WHERE room_id = ? ORDER BY created_at",
            (room_id,),
        ).fetchall()

    sensors = []
    for r in rows:
        schema = json.loads(r["schema_json"])
        sensor_type = schema.get("x-sensor-type", "form")
        sid = r["sensor_id"]
        rid = RoomId(r["room_id"])
        label = r["label"]
        tool_id = r["tool_id"]

        if sensor_type == "qr_checkin":
            threshold = schema.get("x-stale-hours", 48)
            sensors.append(QRCheckInSensorImpl(
                sid, rid, label, schema, threshold, tool_id
            ))
        else:
            sensors.append(FormSensorImpl(sid, rid, label, schema, None, tool_id))

    return sensors


# ---------------------------------------------------------------------------
# Manual sensor builder (Admin-only, Day 4, replaced Day 8)
# ---------------------------------------------------------------------------

_FIELD_TYPES = [
    ("Text",         "string",  ""),
    ("Long text",    "string",  "textarea"),
    ("Number",       "number",  ""),
    ("Whole number", "integer", ""),
    ("Date",         "string",  "date"),
    ("Yes / No",     "boolean", ""),
    ("Dropdown",     "string",  "enum"),
]


class _FieldRow(QWidget):
    removed = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self._name = QWidget.__new__(QWidget)
        from PySide6.QtWidgets import QLineEdit as QLE
        self._name = QLE()
        self._name.setPlaceholderText("field_name")
        self._name.setFixedWidth(180)

        self._type_combo = QComboBox()
        for label, _, _ in _FIELD_TYPES:
            self._type_combo.addItem(label)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)

        self._enum_input = __import__('PySide6.QtWidgets', fromlist=['QLineEdit']).QLineEdit()
        self._enum_input.setPlaceholderText("A, B, C")
        self._enum_input.setVisible(False)
        self._enum_input.setFixedWidth(160)

        self._required = QCheckBox("Required")

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(26, 26)
        remove_btn.clicked.connect(lambda: self.removed.emit(self))

        layout.addWidget(self._name)
        layout.addWidget(self._type_combo)
        layout.addWidget(self._enum_input)
        layout.addWidget(self._required)
        layout.addWidget(remove_btn)
        layout.addStretch()

    def _on_type_changed(self, idx: int) -> None:
        _, ftype, fmt = _FIELD_TYPES[idx]
        self._enum_input.setVisible(ftype == "string" and fmt == "enum")

    def field_def(self):
        name = self._name.text().strip().replace(" ", "_")
        if not name:
            return None
        idx = self._type_combo.currentIndex()
        _, ftype, fmt = _FIELD_TYPES[idx]
        fd = {"type": ftype, "title": self._name.text().strip()}
        if fmt:
            fd["format"] = fmt
        if ftype == "string" and fmt == "enum":
            opts = [o.strip() for o in self._enum_input.text().split(",") if o.strip()]
            fd["enum"] = opts or ["—"]
        return name, fd, self._required.isChecked()


class _AddSensorDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Custom Sensor")
        self.setMinimumWidth(620)
        self._rows: List[_FieldRow] = []
        self._sensor_type = "form"
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        note = QLabel("Custom Sensor — Admin only. Replaced by Tool installation on Day 8.")
        note.setStyleSheet("color: #f9e2af; font-style: italic;")

        form = QFormLayout()
        from PySide6.QtWidgets import QLineEdit as QLE
        self._label_input = QLE()
        self._label_input.setPlaceholderText("Sensor label")
        form.addRow("Label *", self._label_input)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._type_form = QComboBox()
        self._type_form.addItem("Form (field submission)", "form")
        self._type_form.addItem("QR Photo Check-in", "qr_checkin")
        self._type_form.currentIndexChanged.connect(self._on_sensor_type_changed)
        type_row.addWidget(self._type_form)
        type_row.addStretch()
        form.addRow("", type_row)

        # Form fields group
        self._fields_group = QGroupBox("Fields")
        self._fields_layout = QVBoxLayout(self._fields_group)

        add_field_btn = QPushButton("+ Add field")
        add_field_btn.setFixedWidth(110)
        add_field_btn.clicked.connect(self._add_field)
        self._add_field_btn = add_field_btn

        # QR entities group
        self._qr_group = QGroupBox("Entities (section IDs to track)")
        qr_layout = QFormLayout(self._qr_group)
        from PySide6.QtWidgets import QLineEdit as QLE2
        self._entities_input = QLE2()
        self._entities_input.setPlaceholderText("S1=Section 1, S2=Section 2, …")
        self._stale_spin = __import__('PySide6.QtWidgets', fromlist=['QSpinBox']).QSpinBox()
        self._stale_spin.setRange(1, 720)
        self._stale_spin.setValue(48)
        self._stale_spin.setSuffix(" hours")
        qr_layout.addRow("Entities", self._entities_input)
        qr_layout.addRow("Stale threshold", self._stale_spin)
        self._qr_group.hide()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout.addWidget(note)
        layout.addLayout(form)
        layout.addWidget(self._fields_group)
        layout.addWidget(add_field_btn)
        layout.addWidget(self._qr_group)
        layout.addWidget(buttons)
        self._add_field()

    def _on_sensor_type_changed(self, idx: int) -> None:
        self._sensor_type = self._type_form.currentData()
        is_form = self._sensor_type == "form"
        self._fields_group.setVisible(is_form)
        self._add_field_btn.setVisible(is_form)
        self._qr_group.setVisible(not is_form)

    def _add_field(self) -> None:
        row = _FieldRow()
        row.removed.connect(self._remove_field)
        self._rows.append(row)
        self._fields_layout.addWidget(row)

    def _remove_field(self, row) -> None:
        self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def _validate(self) -> None:
        if not self._label_input.text().strip():
            QMessageBox.warning(self, "Required", "Label is required.")
            return
        self.accept()

    def build_sensor(self) -> tuple:
        """Returns (label, schema_json_dict, sensor_type)."""
        label = self._label_input.text().strip()
        sensor_type = self._sensor_type

        if sensor_type == "qr_checkin":
            entities = []
            raw = self._entities_input.text()
            for part in raw.split(","):
                part = part.strip()
                if "=" in part:
                    eid, elabel = part.split("=", 1)
                    entities.append({"id": eid.strip(), "label": elabel.strip()})
                elif part:
                    entities.append({"id": part, "label": part})
            schema = {
                "x-sensor-type": "qr_checkin",
                "x-entities": entities,
                "x-stale-hours": self._stale_spin.value(),
            }
        else:
            properties = {}
            required = []
            for row in self._rows:
                result = row.field_def()
                if not result:
                    continue
                name, fd, is_req = result
                properties[name] = fd
                if is_req:
                    required.append(name)
            schema = {
                "x-sensor-type": "form",
                "type": "object",
                "title": label,
                "properties": properties,
            }
            if required:
                schema["required"] = required

        return label, schema, sensor_type


# ---------------------------------------------------------------------------
# Submission history (hardened)
# ---------------------------------------------------------------------------

def _load_history(sensor_id: str, room_id: str, limit: int = 10) -> List[dict]:
    """Load last N submissions with audit formatting. Includes failed entries."""
    from core.db.connection import get_connection
    from core.audit import format_event
    with get_connection() as conn:
        # Successful submissions from sensor_events
        success_rows = conn.execute(
            "SELECT se.event_id, se.timestamp, se.user_id, se.payload, "
            "u.display_name, pc.photo_path "
            "FROM sensor_events se "
            "LEFT JOIN users u ON se.user_id = u.user_id "
            "LEFT JOIN photo_checkins pc ON se.event_id = pc.event_id "
            "WHERE se.room_id = ? AND se.sensor_id = ? "
            "ORDER BY se.timestamp DESC LIMIT ?",
            (room_id, sensor_id, limit),
        ).fetchall()

        # Failed submissions from audit_log (success=0)
        fail_rows = conn.execute(
            "SELECT timestamp, username, details FROM audit_log "
            "WHERE resource = ? AND action = 'sensor_submitted' "
            "AND success = 0 AND details LIKE ? "
            "ORDER BY seq DESC LIMIT 5",
            (room_id, f'%"{sensor_id}"%'),
        ).fetchall()

    entries = []
    for r in success_rows:
        payload = json.loads(r["payload"])
        summary = ", ".join(f"{k}: {v}" for k, v in list(payload.items())[:3]
                            if k not in ("photo_path", "timestamp"))
        entries.append({
            "ts":         r["timestamp"][:16].replace("T", " "),
            "actor":      r["display_name"] or r["user_id"],
            "message":    summary or "Check-in submitted",
            "photo_path": r["photo_path"],
            "failed":     False,
        })

    for r in fail_rows:
        try:
            d = json.loads(r["details"] or "{}")
        except Exception:
            d = {}
        entries.append({
            "ts":         r["timestamp"][:16].replace("T", " "),
            "actor":      r["username"] or "?",
            "message":    d.get("error", "Validation failed"),
            "photo_path": None,
            "failed":     True,
        })

    entries.sort(key=lambda e: e["ts"], reverse=True)
    return entries[:limit]


# ---------------------------------------------------------------------------
# Sensors tab
# ---------------------------------------------------------------------------

class SensorsView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: Optional[User] = None
        self._room_id: Optional[RoomId] = None
        self._sensors: List = []
        self._selected = None
        self._renderer: Optional[FormRenderer] = None
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        self._add_btn.setVisible(can_manage_room(actor, room_id))
        self._refresh_sensor_list()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left.setFixedWidth(240)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 8, 12)

        hdr = QLabel("Sensors")
        hdr.setFont(QFont("", 13, QFont.Bold))

        self._add_btn = QPushButton("+ Custom Sensor")
        self._add_btn.setFixedHeight(32)
        self._add_btn.setVisible(False)
        self._add_btn.clicked.connect(self._add_sensor)

        self._sensor_list = QListWidget()
        self._sensor_list.currentRowChanged.connect(self._on_sensor_selected)

        ll.addWidget(hdr)
        ll.addWidget(self._add_btn)
        ll.addWidget(self._sensor_list)

        self._right = QWidget()
        self._right_layout = QVBoxLayout(self._right)
        self._right_layout.setContentsMargins(16, 12, 16, 12)
        self._right_layout.addWidget(
            QLabel("Select a sensor from the list.", alignment=Qt.AlignCenter)
        )

        splitter.addWidget(left)
        splitter.addWidget(self._right)
        splitter.setSizes([240, 600])
        layout.addWidget(splitter)

    def _refresh_sensor_list(self) -> None:
        self._sensor_list.clear()
        self._sensors = _load_sensors_for_room(str(self._room_id))
        if not self._sensors:
            item = QListWidgetItem("No sensors registered.")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self._sensor_list.addItem(item)
            return
        for s in self._sensors:
            type_label = "QR" if isinstance(s, QRCheckInSensorImpl) else "Form"
            badge = f" [{type_label}]" if s.tool_id is None else f" [{type_label}]"
            item = QListWidgetItem(f"{s.label}{badge}")
            self._sensor_list.addItem(item)
        self.status_message.emit(f"{len(self._sensors)} sensor(s) loaded")

    def _on_sensor_selected(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._sensors):
            return
        self._selected = self._sensors[idx]
        self._rebuild_right()

    def _rebuild_right(self) -> None:
        while self._right_layout.count():
            item = self._right_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._renderer = None

        sensor = self._selected
        header = QLabel(sensor.label)
        header.setFont(QFont("", 15, QFont.Bold))
        self._right_layout.addWidget(header)

        if isinstance(sensor, QRCheckInSensorImpl):
            self._build_qr_panel(sensor)
        else:
            self._build_form_panel(sensor)

        self._right_layout.addStretch()

    # ── Form sensor panel ─────────────────────────────────────────────────────

    def _build_form_panel(self, sensor: FormSensorImpl) -> None:
        from core.auth.rbac import get_room_role
        role = get_room_role(self._actor, self._room_id)
        can_submit = role == RoomRole.OFFICER

        if can_submit:
            form_group = QGroupBox("Submit")
            fl = QVBoxLayout(form_group)
            self._renderer = FormRenderer(sensor.get_schema())
            submit_btn = QPushButton("Submit")
            submit_btn.setFixedHeight(38)
            submit_btn.clicked.connect(self._on_form_submit)
            fl.addWidget(self._renderer)
            fl.addWidget(submit_btn)
        else:
            form_group = QLabel("View-only access.", styleSheet="color:#6c7086;")

        self._right_layout.addWidget(form_group)
        self._build_history_panel(sensor)

    # ── QR check-in panel ─────────────────────────────────────────────────────

    def _build_qr_panel(self, sensor: QRCheckInSensorImpl) -> None:
        entities = sensor.get_entities()
        if not entities:
            self._right_layout.addWidget(
                QLabel("No entities defined for this sensor.\n"
                       "Edit the sensor to add section IDs.",
                       styleSheet="color:#6c7086;")
            )
            return

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Entity", "Last Check-in", "Status", "Actions"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().hide()

        now = datetime.utcnow()
        stale_ids = sensor.get_stale_entities(
            [e["id"] for e in entities], now
        )

        for ent in entities:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(
                f"{ent.get('label', ent['id'])} ({ent['id']})"
            ))
            last = sensor.get_last_checkin(ent["id"])
            last_str = last.timestamp.strftime("%Y-%m-%d %H:%M") if last else "Never"
            table.setItem(r, 1, QTableWidgetItem(last_str))

            is_stale = ent["id"] in stale_ids
            status_item = QTableWidgetItem("🔴 Stale" if is_stale else "🟢 Fresh")
            if is_stale:
                status_item.setForeground(QColor("#f9e2af"))
            table.setItem(r, 2, status_item)

            # Action buttons
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)

            qr_btn = QPushButton("QR")
            qr_btn.setFixedSize(38, 26)
            entity_id = ent["id"]
            entity_label = ent.get("label", ent["id"])
            qr_btn.clicked.connect(
                lambda _, eid=entity_id, el=entity_label, s=sensor:
                self._show_qr_popup(s, eid, el)
            )

            scan_btn = QPushButton("Scan")
            scan_btn.setFixedSize(44, 26)
            scan_btn.clicked.connect(
                lambda _, eid=entity_id, el=entity_label, s=sensor:
                self._open_checkin(s, eid, el)
            )

            btn_layout.addWidget(qr_btn)
            btn_layout.addWidget(scan_btn)
            table.setCellWidget(r, 3, btn_widget)

        self._right_layout.addWidget(table)
        self._build_history_panel(sensor)

    def _show_qr_popup(self, sensor, entity_id: str, entity_label: str) -> None:
        from PySide6.QtWidgets import QDialog as QD
        dlg = QD(self)
        dlg.setWindowTitle(f"QR: {entity_label}")
        dlg_layout = QVBoxLayout(dlg)
        qr_widget = QRDisplayWidget(entity_id, entity_label)
        qr_widget.set_qr(sensor.generate_qr(entity_id))
        qr_widget.scan_requested.connect(
            lambda eid: self._open_checkin(sensor, eid, entity_label)
        )
        dlg_layout.addWidget(qr_widget)
        dlg.exec()

    def _open_checkin(self, sensor, entity_id: str, entity_label: str) -> None:
        from app.screens.checkin_dialog import CheckInDialog
        dlg = CheckInDialog(self._actor, entity_id, entity_label, sensor, self)
        if dlg.exec() == QDialog.Accepted:
            self._rebuild_right()
            self.status_message.emit(f"Check-in recorded: {entity_label}")
            top = self.window()
            if hasattr(top, "_banner_bar"):
                top._banner_bar.show_banner("Check-in submitted.", kind="success")

    # ── History panel ─────────────────────────────────────────────────────────

    def _build_history_panel(self, sensor) -> None:
        group = QGroupBox("Recent Submissions")
        gl = QVBoxLayout(group)
        hist_list = QListWidget()
        hist_list.setMaximumHeight(200)

        entries = _load_history(str(sensor.sensor_id), str(self._room_id))
        if not entries:
            hist_list.addItem("No submissions yet.")
        else:
            for e in entries:
                item = QListWidgetItem(
                    f"{e['ts']}  {e['actor']}  —  {e['message']}"
                )
                if e["failed"]:
                    item.setForeground(QColor("#f38ba8"))
                    item.setText("✗  " + item.text())

                # Thumbnail for photo check-ins
                if e.get("photo_path"):
                    from pathlib import Path
                    p = Path(e["photo_path"])
                    if p.exists():
                        px = QPixmap(str(p)).scaled(
                            48, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                        item.setData(Qt.DecorationRole, px)

                hist_list.addItem(item)

        gl.addWidget(hist_list)
        self._right_layout.addWidget(group)
        self._history_list = hist_list

    # ── Form submit ───────────────────────────────────────────────────────────

    def _on_form_submit(self) -> None:
        if not self._renderer or not isinstance(self._selected, FormSensorImpl):
            return
        ok, msg = self._renderer.is_valid()
        if not ok:
            QMessageBox.warning(self, "Incomplete", msg)
            return
        payload = self._renderer.collect()
        try:
            self._selected.submit(self._actor, payload)
            self._renderer.reset()
            self._rebuild_right()
            self.status_message.emit("Form submitted")
            top = self.window()
            if hasattr(top, "_banner_bar"):
                top._banner_bar.show_banner("Form submitted successfully.", kind="success")
        except Exception as exc:
            QMessageBox.critical(self, "Submission failed", str(exc))

    # ── Add custom sensor ─────────────────────────────────────────────────────

    def _add_sensor(self) -> None:
        dlg = _AddSensorDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        label, schema, sensor_type = dlg.build_sensor()
        sensor_id = str(uuid.uuid4())
        sensor_service.register(
            sensor_id=sensor_id,
            room_id=str(self._room_id),
            label=label,
            schema=schema,
            tool_id=None,
        )
        self._refresh_sensor_list()
        self.status_message.emit(f"Sensor created: {label}")


from PySide6.QtWidgets import QDialog