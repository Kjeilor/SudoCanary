from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QLineEdit, QFrame,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QPixmap, QFont

from core.auth.auth_service import auth_service
from core.auth.totp import generate_secret, generate_qr_bytes, verify_code


class TOTPSetupScreen(QWidget):
    setup_complete = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._user = None
        self._secret = None
        self._build_ui()

    def set_user(self, user) -> None:
        self._user = user
        self._secret = generate_secret()
        qr_bytes = generate_qr_bytes(self._secret, user.username)
        pixmap = QPixmap()
        pixmap.loadFromData(qr_bytes)
        self._qr.setPixmap(
            pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self._code_input.clear()
        self._error.hide()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setFixedWidth(460)
        layout = QVBoxLayout(card)
        layout.setSpacing(14)
        layout.setContentsMargins(32, 32, 32, 32)

        title = QLabel("Set Up Two-Factor Authentication")
        title.setFont(QFont("", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)

        instructions = QLabel(
            "Scan this QR code with an authenticator app\n"
            "(Google Authenticator, Authy, or similar),\n"
            "then enter the 6-digit code below to confirm."
        )
        instructions.setAlignment(Qt.AlignCenter)
        instructions.setWordWrap(True)

        self._qr = QLabel()
        self._qr.setAlignment(Qt.AlignCenter)
        self._qr.setFixedSize(216, 216)

        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("6-digit code")
        self._code_input.setMaxLength(6)
        self._code_input.setAlignment(Qt.AlignCenter)
        self._code_input.setFixedHeight(40)
        self._code_input.returnPressed.connect(self._verify)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #c0392b;")
        self._error.setAlignment(Qt.AlignCenter)
        self._error.hide()

        confirm_btn = QPushButton("Confirm and Enable MFA")
        confirm_btn.setFixedHeight(42)
        confirm_btn.clicked.connect(self._verify)

        layout.addWidget(title)
        layout.addWidget(instructions)
        layout.addWidget(self._qr, alignment=Qt.AlignCenter)
        layout.addWidget(self._code_input)
        layout.addWidget(self._error)
        layout.addWidget(confirm_btn)

        root.addWidget(card, alignment=Qt.AlignCenter)

    def _verify(self) -> None:
        code = self._code_input.text().strip()
        if not self._secret or not verify_code(self._secret, code):
            self._error.setText("Incorrect code — please try again.")
            self._error.show()
            return
        auth_service.enroll_totp(self._user.user_id, self._secret)
        self._error.hide()
        self.setup_complete.emit()