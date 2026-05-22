"""
Application entry point.

Boot sequence:
  1. initialise_schema() — creates/verifies encrypted DB
  2. QApplication + CanaryWindow
  3. LoginScreen shown immediately

Inactivity: 10-minute QTimer resets on mouse/key events in the home area.
On timeout: session invalidated, user returned to login screen.
"""
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from core.auth.session import session_manager
from core.db.schema import initialise_schema
from app.screens.login import LoginScreen
from app.screens.data_notice import DataNoticeScreen
from app.screens.totp_setup import TOTPSetupScreen
from app.screens.totp_verify import TOTPVerifyScreen
from app.screens.home import HomeScreen

INACTIVITY_MS = 10 * 60 * 1000  # 10 minutes


class CanaryWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Sudo Canary")
        self.setMinimumSize(1280, 800)

        self._session_id: str | None = None

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._login = LoginScreen()
        self._data_notice = DataNoticeScreen()
        self._totp_setup = TOTPSetupScreen()
        self._totp_verify = TOTPVerifyScreen()
        self._home = HomeScreen()

        for screen in (
            self._login, self._data_notice,
            self._totp_setup, self._totp_verify, self._home,
        ):
            self._stack.addWidget(screen)

        # Signal wiring
        self._login.credentials_accepted.connect(self._on_credentials_accepted)
        self._data_notice.notice_accepted.connect(self._on_data_notice_accepted)
        self._totp_setup.setup_complete.connect(self._on_totp_setup_complete)
        self._totp_verify.code_verified.connect(self._on_mfa_verified)

        # Inactivity timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_inactivity_timeout)

        self._stack.setCurrentWidget(self._login)

    # ── Navigation handlers ───────────────────────────────────────────────────

    def _on_credentials_accepted(self, session_id: str, user) -> None:
        self._session_id = session_id
        if not user.first_login_complete:
            self._data_notice.set_user(user)
            self._stack.setCurrentWidget(self._data_notice)
        elif user.totp_secret is None:
            self._totp_setup.set_user(user)
            self._stack.setCurrentWidget(self._totp_setup)
        else:
            self._totp_verify.set_session(session_id)
            self._stack.setCurrentWidget(self._totp_verify)

    def _on_data_notice_accepted(self) -> None:
        user = session_manager.get_user(self._session_id)
        if user is None:
            return
        if user.totp_secret is None:
            self._totp_setup.set_user(user)
            self._stack.setCurrentWidget(self._totp_setup)
        else:
            self._totp_verify.set_session(self._session_id)
            self._stack.setCurrentWidget(self._totp_verify)

    def _on_totp_setup_complete(self) -> None:
        self._totp_verify.set_session(self._session_id)
        self._stack.setCurrentWidget(self._totp_verify)

    def _on_mfa_verified(self) -> None:
        self._timer.start(INACTIVITY_MS)
        self._stack.setCurrentWidget(self._home)

    # ── Inactivity ────────────────────────────────────────────────────────────

    def _reset_inactivity_timer(self) -> None:
        if self._session_id:
            session_manager.touch(self._session_id)
        self._timer.start(INACTIVITY_MS)

    def _on_inactivity_timeout(self) -> None:
        if self._session_id:
            session_manager.invalidate(self._session_id)
            self._session_id = None
        self._login.reset()
        self._stack.setCurrentWidget(self._login)

    def mousePressEvent(self, event) -> None:
        if self._stack.currentWidget() is self._home:
            self._reset_inactivity_timer()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._stack.currentWidget() is self._home:
            self._reset_inactivity_timer()
        super().keyPressEvent(event)


def main() -> None:
    initialise_schema()
    app = QApplication(sys.argv)
    app.setApplicationName("Sudo Canary")
    window = CanaryWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()