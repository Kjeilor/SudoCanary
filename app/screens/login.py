from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QFrame,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont

from core.auth.auth_service import auth_service
from core.auth.session import session_manager


class LoginScreen(QWidget):
    credentials_accepted = Signal(str, object)  # session_id, User

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignCenter)

        card = QFrame()
        card.setFixedWidth(400)
        layout = QVBoxLayout(card)
        layout.setSpacing(16)
        layout.setContentsMargins(32, 32, 32, 32)

        title = QLabel("Sudo Canary")
        title.setFont(QFont("", 26, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.hide()   # hidden — replaced by SVG below

        # SVG logo — shown above the form
        try:
            from PySide6.QtSvgWidgets import QSvgWidget
            logo_widget = QSvgWidget("app/assets/Sudo Canary Logo.svg")
            logo_widget.setFixedSize(220, 52)
            _logo: QWidget = logo_widget
        except Exception:
            _logo = QLabel("Sudo Canary")
            _logo.setFont(QFont("", 22, QFont.Bold))
            _logo.setStyleSheet("color: #29AB87;")
        _logo.setToolTip("Sudo Canary — Institutional Intelligence Engine")

        subtitle = QLabel("Institutional Intelligence Engine")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #AAAAAA; font-size: 12px;")

        form = QFormLayout()
        form.setSpacing(10)
        self._username = QLineEdit()
        self._username.setPlaceholderText("Username")
        self._username.setFixedHeight(36)
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.Password)
        self._password.setPlaceholderText("Password")
        self._password.setFixedHeight(36)
        self._password.returnPressed.connect(self._attempt_login)
        form.addRow("Username", self._username)
        form.addRow("Password", self._password)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #c0392b;")
        self._error.setAlignment(Qt.AlignCenter)
        self._error.hide()

        btn = QPushButton("Sign In")
        btn.setFixedHeight(42)
        btn.clicked.connect(self._attempt_login)

        layout.addWidget(_logo, alignment=Qt.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addWidget(self._error)
        layout.addWidget(btn)

        root.addWidget(card, alignment=Qt.AlignCenter)

        # Ateker mark below the card
        try:
            from PySide6.QtSvgWidgets import QSvgWidget
            ateker = QSvgWidget("app/assets/From Ateker Logo.svg")
            ateker.setFixedSize(140, 25)
            root.addSpacing(16)
            root.addWidget(ateker, alignment=Qt.AlignCenter)
        except Exception:
            ateker_lbl = QLabel("A product of Ateker")
            ateker_lbl.setAlignment(Qt.AlignCenter)
            ateker_lbl.setStyleSheet("color: #6B7280; font-size: 11px;")
            root.addSpacing(16)
            root.addWidget(ateker_lbl)

    def _attempt_login(self) -> None:
        username = self._username.text().strip()
        password = self._password.text()

        if not username or not password:
            self._show_error("Please enter your username and password.")
            return

        user = auth_service.verify_password(username, password)
        if user is None:
            self._show_error("Invalid credentials. Please try again.")
            return

        self._error.hide()
        session = session_manager.create_session(user)
        self.credentials_accepted.emit(session.session_id, user)

    def _show_error(self, msg: str) -> None:
        self._error.setText(msg)
        self._error.show()

    def reset(self) -> None:
        self._username.clear()
        self._password.clear()
        self._error.hide()