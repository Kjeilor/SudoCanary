"""
app/screens/checkin_dialog.py

Modal check-in dialog for the QR photo check-in sensor.
Use exec() — blocks until the user submits or cancels.

Flow:
  1. Entity label shown at top
  2. Timestamp auto-set (read-only)
  3. Optional GPS lat/lon (QDoubleSpinBox — None stored if unchecked, not 0.0)
  4. Photo select button → QFileDialog (images only)
  5. Thumbnail preview once photo is chosen
  6. Submit disabled until photo selected
  7. On submit: compress → save → write sensor_event + photo_checkins + audit_log
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from core.models.user import User
from core.sdk.types import RoomId, SensorId


class CheckInDialog(QDialog):
    """
    Modal photo check-in dialog.

    After exec() returns Accepted, the check-in has already been written
    to the database. The caller does not need to call anything else.
    """

    def __init__(
        self,
        actor: User,
        entity_id: str,
        entity_label: str,
        sensor,              # QRCheckInSensorImpl
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Check-in: {entity_label}")
        self.setMinimumWidth(420)
        self._actor = actor
        self._entity_id = entity_id
        self._sensor = sensor
        self._photo_path: Optional[Path] = None
        self._build_ui(entity_label)

    def _build_ui(self, entity_label: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        # Entity
        form.addRow("Entity", QLabel(entity_label))

        # Timestamp (read-only)
        self._ts_label = QLabel(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
        form.addRow("Timestamp", self._ts_label)

        # GPS — optional; None if unchecked
        self._use_gps = QCheckBox("Include GPS coordinates")
        self._use_gps.stateChanged.connect(self._on_gps_toggled)

        self._lat_spin = QDoubleSpinBox()
        self._lat_spin.setRange(-90.0, 90.0)
        self._lat_spin.setDecimals(6)
        self._lat_spin.setEnabled(False)
        self._lat_spin.setSpecialValueText("")

        self._lon_spin = QDoubleSpinBox()
        self._lon_spin.setRange(-180.0, 180.0)
        self._lon_spin.setDecimals(6)
        self._lon_spin.setEnabled(False)

        form.addRow("", self._use_gps)
        form.addRow("Latitude", self._lat_spin)
        form.addRow("Longitude", self._lon_spin)

        # Photo
        self._photo_btn = QPushButton("Select photo…")
        self._photo_btn.clicked.connect(self._pick_photo)

        self._photo_name_label = QLabel("No photo selected")
        self._photo_name_label.setStyleSheet("color: #6c7086;")

        self._thumbnail = QLabel()
        self._thumbnail.setFixedSize(120, 90)
        self._thumbnail.setAlignment(Qt.AlignCenter)
        self._thumbnail.setStyleSheet("background-color: #313244; border-radius: 4px;")
        self._thumbnail.hide()

        form.addRow("Photo *", self._photo_btn)
        form.addRow("", self._photo_name_label)
        form.addRow("", self._thumbnail)

        # Buttons
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self._buttons.button(QDialogButtonBox.Ok).setText("Submit check-in")
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self._buttons.accepted.connect(self._submit)
        self._buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(self._buttons)

    def _on_gps_toggled(self, state: int) -> None:
        enabled = state == Qt.Checked
        self._lat_spin.setEnabled(enabled)
        self._lon_spin.setEnabled(enabled)

    def _pick_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select photo", "",
            "Images (*.jpg *.jpeg *.png *.bmp *.tiff)"
        )
        if not path:
            return
        self._photo_path = Path(path)
        self._photo_name_label.setText(self._photo_path.name)
        self._photo_name_label.setStyleSheet("color: #cdd6f4;")

        # Thumbnail preview
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self._thumbnail.setPixmap(
                pixmap.scaled(120, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self._thumbnail.show()

        self._buttons.button(QDialogButtonBox.Ok).setEnabled(True)

    def _submit(self) -> None:
        if not self._photo_path:
            return

        gps_lat: Optional[float] = None
        gps_lon: Optional[float] = None
        if self._use_gps.isChecked():
            gps_lat = self._lat_spin.value()
            gps_lon = self._lon_spin.value()

        try:
            self._sensor.on_checkin(
                entity_id=self._entity_id,
                photo_source=self._photo_path,
                user_id=self._actor.user_id,
                username=self._actor.username,
                gps_lat=gps_lat,
                gps_lon=gps_lon,
            )
            self.accept()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Check-in failed", str(exc))