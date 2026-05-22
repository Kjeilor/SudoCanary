from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QLineEdit, QFrame,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont

from core.auth.auth_service import auth_service


class TOTPVerifyScreen(QWidget):
    code_verified = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session_id: str | None = None
        self._build_ui()

    def set_session(self, session_id: str) -> None:
        self._session_id = session_id
        self._code_input.clear()
        self._error.hide()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setFixedWidth(360)
        layout = QVBoxLayout(card)
        layout.setSpacing(14)
        layout.setContentsMargins(32, 32, 32, 32)

        title = QLabel("Two-Factor Authentication")
        title.setFont(QFont("", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)

        sub = QLabel("Enter the 6-digit code from your authenticator app.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)

        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("000000")
        self._code_input.setMaxLength(6)
        self._code_input.setAlignment(Qt.AlignCenter)
        self._code_input.setFixedHeight(40)
        self._code_input.returnPressed.connect(self._verify)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #c0392b;")
        self._error.setAlignment(Qt.AlignCenter)
        self._error.hide()

        verify_btn = QPushButton("Verify")
        verify_btn.setFixedHeight(42)
        verify_btn.clicked.connect(self._verify)

        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addSpacing(8)
        layout.addWidget(self._code_input)
        layout.addWidget(self._error)
        layout.addWidget(verify_btn)

        root.addWidget(card, alignment=Qt.AlignCenter)

    def _verify(self) -> None:
        code = self._code_input.text().strip()
        if auth_service.verify_totp(self._session_id, code):
            self._error.hide()
            self.code_verified.emit()
        else:
            self._error.setText("Incorrect code. Please try again.")
            self._error.show()