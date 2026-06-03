"""
Application entry point — Day 4.

Window structure:
  QMainWindow
    QStatusBar (bottom, always visible)
    central widget
      TopBar (hidden during auth flows)
      BannerBar (collapses when empty)
      QStackedWidget
        LoginScreen / DataNoticeScreen / TOTPSetupScreen / TOTPVerifyScreen
        StagingArea   ← shown after MFA
        RoomView      ← shown when room selected
        SettingsScreen
"""
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from core.auth.session import session_manager
from core.db.schema import initialise_schema

INACTIVITY_MS = 10 * 60 * 1000   # 10 minutes
WARN_BEFORE_MS = 2 * 60 * 1000   # warn 2 minutes before logout


class CanaryWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Sudo Canary")
        self.setMinimumSize(1280, 800)

        self._session_id: str | None = None

        # ── Status bar ────────────────────────────────────────────────
        from app.widgets.status_bar_widget import CanaryStatusBar
        self._status_bar = CanaryStatusBar()
        self.setStatusBar(self._status_bar)

        # ── Central widget ────────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        from app.widgets.top_bar import TopBar
        self._top_bar = TopBar()
        self._top_bar.setVisible(False)

        from app.widgets.banner_bar import BannerBar
        self._banner_bar = BannerBar()

        self._stack = QStackedWidget()

        root.addWidget(self._top_bar)
        root.addWidget(self._banner_bar)
        root.addWidget(self._stack)

        # ── Screens ───────────────────────────────────────────────────
        from app.screens.login import LoginScreen
        from app.screens.data_notice import DataNoticeScreen
        from app.screens.totp_setup import TOTPSetupScreen
        from app.screens.totp_verify import TOTPVerifyScreen
        from app.screens.staging import StagingArea
        from app.screens.room_view import RoomView
        from app.screens.settings import SettingsScreen

        self._login        = LoginScreen()
        self._data_notice  = DataNoticeScreen()
        self._totp_setup   = TOTPSetupScreen()
        self._totp_verify  = TOTPVerifyScreen()
        self._staging      = StagingArea()
        self._room_view    = RoomView()
        self._settings     = SettingsScreen()

        for screen in (
            self._login, self._data_notice, self._totp_setup,
            self._totp_verify, self._staging, self._room_view, self._settings,
        ):
            self._stack.addWidget(screen)

        # ── Signal wiring ─────────────────────────────────────────────
        self._login.credentials_accepted.connect(self._on_credentials_accepted)
        self._data_notice.notice_accepted.connect(self._on_data_notice_accepted)
        self._totp_setup.setup_complete.connect(self._on_totp_setup_complete)
        self._totp_verify.code_verified.connect(self._on_mfa_verified)

        self._staging.room_selected.connect(self._on_room_selected)
        self._staging.settings_requested.connect(self._show_settings)

        self._top_bar.rooms_clicked.connect(self._show_staging)
        self._top_bar.settings_clicked.connect(self._show_settings)

        self._settings.back_requested.connect(self._show_staging)

        self._room_view.status_message.connect(self._status_bar.set_message)
        self._room_view.notice_count_changed.connect(self._top_bar.set_notification_count)

        # ── Inactivity timers ─────────────────────────────────────────
        self._inactivity_timer = QTimer(self)
        self._inactivity_timer.setSingleShot(True)
        self._inactivity_timer.timeout.connect(self._on_inactivity_timeout)

        self._warn_timer = QTimer(self)
        self._warn_timer.setSingleShot(True)
        self._warn_timer.timeout.connect(self._on_inactivity_warning)

        # ── Canary compute timer (configurable interval) ───────────────
        self._canary_timer = QTimer(self)
        self._canary_timer.timeout.connect(self._on_canary_tick)
        self._canary_interval_ms = 5 * 60 * 1000  # default 5 minutes

        self._stack.setCurrentWidget(self._login)

    # ── Auth flow ─────────────────────────────────────────────────────────────

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
        self._top_bar.setVisible(True)
        self._show_staging()
        self._start_inactivity_timers()
        self._start_canary_timer()
        # Apply user's saved theme preference
        try:
            from app.theme import apply_theme
            from core.db.connection import get_connection
            user = session_manager.get_user(self._session_id)
            if user:
                with get_connection() as conn:
                    row = conn.execute(
                        "SELECT theme FROM user_preferences WHERE user_id=?",
                        (str(user.user_id),),
                    ).fetchone()
                if row and row["theme"]:
                    apply_theme(row["theme"])
        except Exception:
            pass

    def _start_canary_timer(self) -> None:
        """Start (or restart) the Canary timer using the user's saved interval."""
        interval_ms = self._canary_interval_ms
        if self._session_id:
            try:
                from core.db.connection import get_connection
                user = session_manager.get_user(self._session_id)
                if user:
                    with get_connection() as conn:
                        row = conn.execute(
                            "SELECT compute_interval_minutes FROM user_preferences "
                            "WHERE user_id=?", (str(user.user_id),)
                        ).fetchone()
                    if row and row["compute_interval_minutes"]:
                        interval_ms = row["compute_interval_minutes"] * 60 * 1000
            except Exception:
                pass
        self._canary_interval_ms = interval_ms
        self._canary_timer.start(interval_ms)

    def _on_canary_tick(self) -> None:
        """Periodic Canary recompute — fires for the current room if in one."""
        try:
            from core.canary_engine import canary_engine
            if self._stack.currentWidget() is self._room_view:
                # Recompute current room
                if hasattr(self._room_view, '_room_id') and self._room_view._room_id:
                    canary_engine.compute(self._room_view._room_id)
            elif self._stack.currentWidget() is self._staging:
                # Recompute all accessible rooms for status dots
                user = session_manager.get_user(self._session_id)
                if user:
                    from core.room_impl import RoomAPIImpl
                    for room in RoomAPIImpl(user).list_rooms():
                        try:
                            canary_engine.compute(room["room_id"])
                        except Exception:
                            pass
        except Exception:
            pass

    # ── Navigation ────────────────────────────────────────────────────────────

    def _show_staging(self) -> None:
        user = session_manager.get_user(self._session_id)
        if user is None:
            return
        self._staging.load_rooms(user)
        self._top_bar.set_context(None)
        self._stack.setCurrentWidget(self._staging)
        self._status_bar.set_message("Ready")

    def _on_room_selected(self, room_id: str, room_name: str) -> None:
        user = session_manager.get_user(self._session_id)
        if user is None:
            return
        self._room_view.load_room(user, room_id, room_name)
        self._top_bar.set_context(room_name)
        self._stack.setCurrentWidget(self._room_view)
        self._reset_inactivity_timers()

    def _show_settings(self) -> None:
        user = session_manager.get_user(self._session_id)
        if user:
            self._settings.load_user(user)
        self._top_bar.set_context(None)
        self._stack.setCurrentWidget(self._settings)

    # ── Inactivity ────────────────────────────────────────────────────────────

    def _start_inactivity_timers(self) -> None:
        self._inactivity_timer.start(INACTIVITY_MS)
        self._warn_timer.start(INACTIVITY_MS - WARN_BEFORE_MS)

    def _reset_inactivity_timers(self) -> None:
        if self._session_id:
            session_manager.touch(self._session_id)
        self._banner_bar.clear_all()
        self._start_inactivity_timers()

    def _on_inactivity_warning(self) -> None:
        self._banner_bar.show_banner(
            "Session expires in 2 minutes due to inactivity.", kind="warning"
        )

    def _on_inactivity_timeout(self) -> None:
        if self._session_id:
            session_manager.invalidate(self._session_id)
            self._session_id = None
        self._banner_bar.clear_all()
        self._top_bar.setVisible(False)
        self._login.reset()
        self._stack.setCurrentWidget(self._login)
        self._status_bar.set_message("Session expired. Please sign in again.")

    def mousePressEvent(self, event) -> None:
        if self._session_id and self._stack.currentWidget() not in (
            self._login, self._data_notice, self._totp_setup, self._totp_verify
        ):
            self._reset_inactivity_timers()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._session_id and self._stack.currentWidget() not in (
            self._login, self._data_notice, self._totp_setup, self._totp_verify
        ):
            self._reset_inactivity_timers()
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        from core.tiles.tile_server import tile_server
        tile_server.stop()
        super().closeEvent(event)


def main() -> None:
    initialise_schema()

    # Start tile server before the window appears
    from core.tiles.tile_server import tile_server
    tile_server.start()
    app = QApplication(sys.argv)
    app.setApplicationName("Sudo Canary")

    # Window icon
    from PySide6.QtGui import QIcon
    app.setWindowIcon(QIcon("app/assets/Sudo Canary Icon.svg"))

    # Apply theme — dark by default, loads user preference after login
    from app.theme import apply_theme
    apply_theme("dark")

    window = CanaryWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()