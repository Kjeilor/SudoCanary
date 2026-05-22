"""Home screen placeholder — replaced Day 3 with real room navigation."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class HomeScreen(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel("Sudo Canary")
        label.setFont(QFont("", 28, QFont.Bold))
        label.setAlignment(Qt.AlignCenter)
        sub = QLabel("Day 3: room navigation goes here")
        sub.setAlignment(Qt.AlignCenter)
        layout.addWidget(label, alignment=Qt.AlignCenter)
        layout.addWidget(sub, alignment=Qt.AlignCenter)