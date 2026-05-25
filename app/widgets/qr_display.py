"""
app/widgets/qr_display.py

Reusable widget that renders a QR code PNG from bytes.
"Save QR" writes the PNG to a user-chosen path.
"Simulate Scan" emits scan_requested(entity_id) — the parent screen
opens checkin_dialog.py for the named entity.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)


class QRDisplayWidget(QWidget):
    scan_requested = Signal(str)  # entity_id

    def __init__(self, entity_id: str, entity_label: str, parent=None) -> None:
        super().__init__(parent)
        self._entity_id = entity_id
        self._png_bytes: bytes | None = None
        self._build_ui(entity_label)

    def set_qr(self, png_bytes: bytes) -> None:
        """Load and display QR code from PNG bytes."""
        self._png_bytes = png_bytes
        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes)
        self._qr_label.setPixmap(
            pixmap.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _build_ui(self, entity_label: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel(entity_label)
        title.setAlignment(Qt.AlignCenter)

        self._qr_label = QLabel("Generating…")
        self._qr_label.setFixedSize(180, 180)
        self._qr_label.setAlignment(Qt.AlignCenter)
        self._qr_label.setStyleSheet("background-color: #ffffff; border-radius: 4px;")

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save QR")
        save_btn.setFixedHeight(30)
        save_btn.clicked.connect(self._save_qr)

        scan_btn = QPushButton("Simulate Scan")
        scan_btn.setFixedHeight(30)
        scan_btn.clicked.connect(lambda: self.scan_requested.emit(self._entity_id))

        btn_row.addWidget(save_btn)
        btn_row.addWidget(scan_btn)

        layout.addWidget(title)
        layout.addWidget(self._qr_label, alignment=Qt.AlignCenter)
        layout.addLayout(btn_row)

    def _save_qr(self) -> None:
        if not self._png_bytes:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save QR Code",
            f"qr_{self._entity_id}.png",
            "PNG Images (*.png)"
        )
        if path:
            with open(path, "wb") as f:
                f.write(self._png_bytes)