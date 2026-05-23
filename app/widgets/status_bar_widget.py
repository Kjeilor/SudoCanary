"""Connectivity-aware status bar. Left: context message. Right: Online/Offline pill."""
from __future__ import annotations

import socket

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel, QStatusBar, QWidget, QHBoxLayout


def _check_online() -> bool:
    try:
        socket.setdefaulttimeout(2)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("8.8.8.8", 53))
        return True
    except OSError:
        return False


class CanaryStatusBar(QStatusBar):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(False)

        self._context_label = QLabel("Ready")
        self._pill = QLabel("🟢 Online")
        self._pill.setToolTip(
            "Online — map tiles can refresh. All data is stored locally regardless of connectivity."
        )

        self.addWidget(self._context_label, stretch=1)
        self.addPermanentWidget(self._pill)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(30_000)
        self._refresh()

    def set_message(self, msg: str) -> None:
        self._context_label.setText(msg)

    def _refresh(self) -> None:
        online = _check_online()
        self._pill.setText("🟢 Online" if online else "🔴 Offline")