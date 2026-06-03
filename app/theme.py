"""
app/theme.py

Theme service. Apply dark or light theme by loading QSS files.
Sidebar, top bar, and status bar are always dark in both themes.
Live switching — no restart required.
"""
from __future__ import annotations

import os
from pathlib import Path

THEMES = ("dark", "light")
_STYLES_DIR = Path(__file__).parent / "styles"


def apply_theme(theme: str) -> None:
    """
    Load and apply a QSS theme.
    theme: "dark" | "light" | "system"
    Falls back to dark.qss if the file is missing.
    """
    from PySide6.QtWidgets import QApplication

    if theme == "system":
        from PySide6.QtGui import QPalette
        app = QApplication.instance()
        if app:
            is_dark = app.palette().color(QPalette.ColorRole.Window).lightness() < 128
            theme = "dark" if is_dark else "light"
        else:
            theme = "dark"

    qss_path = _STYLES_DIR / f"{theme}.qss"
    if not qss_path.exists():
        qss_path = _STYLES_DIR / "dark.qss"

    app = QApplication.instance()
    if app and qss_path.exists():
        app.setStyleSheet(qss_path.read_text())