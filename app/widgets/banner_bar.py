"""
Transient banner system.
Banners stack vertically below the top bar. Each can be dismissed manually.
Green banners auto-dismiss after 4 seconds. All others persist.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

_COLOURS = {
    "info":    ("#1e3a5f", "#90caf9"),
    "warning": ("#3d2f00", "#ffcc02"),
    "error":   ("#4a0f0f", "#ff6b6b"),
    "success": ("#0f3a1f", "#69db7c"),
}


class _Banner(QWidget):
    def __init__(self, message: str, kind: str, on_close) -> None:
        super().__init__()
        bg, fg = _COLOURS.get(kind, _COLOURS["info"])
        self.setStyleSheet(f"background-color: {bg}; border-radius: 0px;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 8, 8)

        label = QLabel(message)
        label.setStyleSheet(f"color: {fg}; background: transparent;")
        label.setWordWrap(True)

        close_btn = QPushButton("✕")
        close_btn.setFlat(True)
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(f"color: {fg}; background: transparent;")
        close_btn.clicked.connect(on_close)

        layout.addWidget(label, stretch=1)
        layout.addWidget(close_btn)


class BannerBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(1)
        self.hide()

    def show_banner(
        self,
        message: str,
        kind: str = "info",
        auto_dismiss: bool = False,
    ) -> None:
        banner = _Banner(message, kind, lambda: self._remove(banner))
        self._layout.addWidget(banner)
        self.show()

        if auto_dismiss or kind == "success":
            QTimer.singleShot(4000, lambda: self._remove(banner))

    def _remove(self, banner: _Banner) -> None:
        banner.setParent(None)
        banner.deleteLater()
        if self._layout.count() == 0:
            self.hide()

    def clear_all(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.hide()