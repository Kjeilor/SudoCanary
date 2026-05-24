"""
app/screens/sensors.py

Sensors tab — live.

Left panel: list of sensors registered in this room.
Right panel: selected sensor's form (FormRenderer) + submission history.

Manual sensor builder: Admin-only dialog that creates a custom sensor
directly in the DB. Labelled "Custom Sensor" in the UI.
Replaced by Tool installation flow on Day 8.

Role gate:
  Officer / Field Officer: can submit forms.
  Viewer: sees submission history only, no form.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QVBoxLayout, QWidget,
)

from core.auth.rbac import can_manage_room, require_room_access
from core.models.user import RoomRole, User
from core.sdk.types import RoomId
from core.sensors.form_sensor import FormSensorImpl, sensor_service
from app.widgets.form_renderer import FormRenderer


# ---------------------------------------------------------------------------
# Manual sensor builder dialog (Admin only, replaced Day 8)
# ---------------------------------------------------------------------------

_FIELD_TYPES = [
    ("Text",          "string",  ""),
    ("Long text",     "string",  "textarea"),
    ("Number",        "number",  ""),
    ("Whole number",  "integer", ""),
    ("Date",          "string",  "date"),
    ("Yes / No",      "boolean", ""),
    ("Dropdown",      "string",  "enum"),
]


class _FieldRow(QWidget):
    removed = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Field name (e.g. road_condition)")
        self._name.setFixedWidth(200)

        self._type_combo = QComboBox()
        for label, _, _ in _FIELD_TYPES:
            self._type_combo.addItem(label)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)

        self._enum_input = QLineEdit()
        self._enum_input.setPlaceholderText("Options: A, B, C")
        self._enum_input.setVisible(False)
        self._enum_input.setFixedWidth(180)

        self._required = QCheckBox("Required")

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(28, 28)
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

    def field_def(self) -> Optional[dict]:
        name = self._name.text().strip().replace(" ", "_")
        if not name:
            return None
        idx = self._type_combo.currentIndex()
        _, ftype, fmt = _FIELD_TYPES[idx]
        fd: dict = {"type": ftype, "title": self._name.text().strip()}
        if fmt:
            fd["format"] = fmt
        if ftype == "string" and fmt == "enum":
            options = [o.strip() for o in self._enum_input.text().split(",") if o.strip()]
            fd["enum"] = options or ["—"]
        return name, fd, self._required.isChecked()


class _AddSensorDialog(QDialog):
    """
    Admin-only manual sensor builder.
    Produces a JSON Schema from field definitions and registers the sensor.
    Labelled 'Custom Sensor' — replaced by Tool installation on Day 8.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Custom Sensor")
        self.setMinimumWidth(640)
        self._rows: List[_FieldRow] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        note = QLabel(
            "Custom Sensor — Admin only. "
            "Replaced by Tool installation on Day 8."
        )
        note.setStyleSheet("color: #f9e2af; font-style: italic;")

        form = QFormLayout()
        self._label_input = QLineEdit()
        self._label_input.setPlaceholderText("e.g. Road Condition Survey")
        form.addRow("Sensor label *", self._label_input)

        self._fields_group = QGroupBox("Fields")
        self._fields_layout = QVBoxLayout(self._fields_group)
        self._fields_layout.setSpacing(4)

        add_field_btn = QPushButton("+ Add field")
        add_field_btn.setFixedWidth(120)
        add_field_btn.clicked.connect(self._add_field)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout.addWidget(note)
        layout.addLayout(form)
        layout.addWidget(self._fields_group)
        layout.addWidget(add_field_btn)
        layout.addWidget(buttons)

        self._add_field()  # start with one field

    def _add_field(self) -> None:
        row = _FieldRow()
        row.removed.connect(self._remove_field)
        self._rows.append(row)
        self._fields_layout.addWidget(row)

    def _remove_field(self, row: _FieldRow) -> None:
        self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def _validate(self) -> None:
        if not self._label_input.text().strip():
            QMessageBox.warning(self, "Required", "Sensor label is required.")
            return
        if not self._rows:
            QMessageBox.warning(self, "Required", "Add at least one field.")
            return
        self.accept()

    def build_schema(self) -> tuple[str, dict, list[str]]:
        """Returns (label, json_schema, required_fields)."""
        label = self._label_input.text().strip()
        properties = {}
        required = []
        for row in self._rows:
            result = row.field_def()
            if result is None:
                continue
            name, fd, is_required = result
            properties[name] = fd
            if is_required:
                required.append(name)

        schema = {
            "type": "object",
            "title": label,
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return label, schema, required


# ---------------------------------------------------------------------------
# Sensors tab
# ---------------------------------------------------------------------------

class SensorsView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: Optional[User] = None
        self._room_id: Optional[RoomId] = None
        self._sensors: List[FormSensorImpl] = []
        self._selected: Optional[FormSensorImpl] = None
        self._renderer: Optional[FormRenderer] = None
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        is_officer = can_manage_room(actor, room_id)
        self._add_btn.setVisible(is_officer)
        self._refresh_sensor_list()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)

        # Left panel — sensor list
        left = QWidget()
        left.setFixedWidth(240)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 8, 12)

        sensors_header = QLabel("Sensors")
        sensors_header.setFont(QFont("", 13, QFont.Bold))

        self._add_btn = QPushButton("+ Custom Sensor")
        self._add_btn.setFixedHeight(32)
        self._add_btn.setVisible(False)
        self._add_btn.clicked.connect(self._add_sensor)

        self._sensor_list = QListWidget()
        self._sensor_list.currentRowChanged.connect(self._on_sensor_selected)

        left_layout.addWidget(sensors_header)
        left_layout.addWidget(self._add_btn)
        left_layout.addWidget(self._sensor_list)

        # Right panel — form + history
        self._right = QWidget()
        self._right_layout = QVBoxLayout(self._right)
        self._right_layout.setContentsMargins(16, 12, 16, 12)
        self._empty_right = QLabel("Select a sensor from the list.")
        self._empty_right.setStyleSheet("color: #6c7086;")
        self._empty_right.setAlignment(Qt.AlignCenter)
        self._right_layout.addWidget(self._empty_right)

        splitter.addWidget(left)
        splitter.addWidget(self._right)
        splitter.setSizes([240, 600])
        layout.addWidget(splitter)

    # ── Sensor list ───────────────────────────────────────────────────────────

    def _refresh_sensor_list(self) -> None:
        self._sensor_list.clear()
        self._sensors = sensor_service.load_for_room(str(self._room_id))

        if not self._sensors:
            item = QListWidgetItem("No sensors registered.")
            item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            self._sensor_list.addItem(item)
            return

        for sensor in self._sensors:
            last = sensor.last_submission_at()
            last_str = last.strftime("%Y-%m-%d %H:%M") if last else "No submissions"
            badge = " [Custom]" if sensor.tool_id is None else ""
            item = QListWidgetItem(f"{sensor.label}{badge}\n{last_str}")
            self._sensor_list.addItem(item)

        self.status_message.emit(f"{len(self._sensors)} sensor(s) loaded")

    def _on_sensor_selected(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._sensors):
            return
        self._selected = self._sensors[idx]
        self._rebuild_right_panel()

    # ── Right panel ───────────────────────────────────────────────────────────

    def _rebuild_right_panel(self) -> None:
        sensor = self._selected
        if not sensor:
            return

        # Clear right panel
        while self._right_layout.count():
            item = self._right_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._empty_right = None

        header = QLabel(sensor.label)
        header.setFont(QFont("", 15, QFont.Bold))

        from core.auth.rbac import get_room_role
        role = get_room_role(self._actor, self._room_id)
        can_submit = role == RoomRole.OFFICER

        if can_submit:
            form_group = QGroupBox("Submit")
            form_layout = QVBoxLayout(form_group)
            self._renderer = FormRenderer(sensor.get_schema())
            submit_btn = QPushButton("Submit")
            submit_btn.setFixedHeight(38)
            submit_btn.clicked.connect(self._on_submit)
            form_layout.addWidget(self._renderer)
            form_layout.addWidget(submit_btn)
        else:
            form_group = QLabel("You have view-only access to this sensor.")
            form_group.setStyleSheet("color: #6c7086; font-style: italic;")
            self._renderer = None

        # Submission history
        history_group = QGroupBox("Recent Submissions")
        history_layout = QVBoxLayout(history_group)
        self._history_list = QListWidget()
        self._history_list.setMaximumHeight(200)
        history_layout.addWidget(self._history_list)
        self._refresh_history()

        self._right_layout.addWidget(header)
        self._right_layout.addWidget(form_group)
        self._right_layout.addWidget(history_group)
        self._right_layout.addStretch()

    def _refresh_history(self) -> None:
        if not self._selected or not self._history_list:
            return
        self._history_list.clear()
        events = self._selected.read_submissions(limit=10)
        if not events:
            self._history_list.addItem("No submissions yet.")
            return
        for ev in events:
            ts = ev.timestamp.strftime("%Y-%m-%d %H:%M")
            summary = ", ".join(f"{k}: {v}" for k, v in list(ev.payload.items())[:3])
            self._history_list.addItem(f"{ts}  —  {summary}")

    # ── Submission ────────────────────────────────────────────────────────────

    def _on_submit(self) -> None:
        if not self._renderer or not self._selected:
            return
        ok, msg = self._renderer.is_valid()
        if not ok:
            QMessageBox.warning(self, "Incomplete form", msg)
            return
        payload = self._renderer.collect()
        try:
            self._selected.submit(self._actor, payload)
            self._renderer.reset()
            self._refresh_history()
            self._refresh_sensor_list()
            self.status_message.emit("Form submitted")
            # green success banner via parent
            from app.widgets.banner_bar import BannerBar
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
        label, schema, _ = dlg.build_schema()
        sensor_id = str(uuid.uuid4())
        sensor_service.register(
            sensor_id=sensor_id,
            room_id=str(self._room_id),
            label=label,
            schema=schema,
            tool_id=None,  # None = Custom Sensor, not from a Tool
        )
        self._refresh_sensor_list()
        self.status_message.emit(f"Sensor \"{label}\" created")