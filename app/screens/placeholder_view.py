"""Empty state placeholder for tabs not yet built."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderView(QWidget):
    def __init__(self, label: str, coming_day: str = "", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("🚧")
        icon.setFont(QFont("", 32))
        icon.setAlignment(Qt.AlignCenter)

        title = QLabel(label)
        title.setFont(QFont("", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)

        sub = QLabel(f"Coming {coming_day}" if coming_day else "Coming soon")
        sub.setStyleSheet("color: #6c7086;")
        sub.setAlignment(Qt.AlignCenter)

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(sub)