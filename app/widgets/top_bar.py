from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont


class TopBar(QWidget):
    rooms_clicked         = Signal()
    settings_clicked      = Signal()
    profile_clicked       = Signal()
    notifications_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(52)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(8)

        try:
            from PySide6.QtSvgWidgets import QSvgWidget
            logo = QSvgWidget("app/assets/Sudo Canary Logo.svg")
            logo.setFixedSize(140, 32)
        except Exception:
            logo = QLabel("Sudo Canary")
            logo.setFont(QFont("", 14, QFont.Bold))
            logo.setStyleSheet("color: #29AB87;")

        self._rooms_btn = QPushButton("Rooms")
        self._rooms_btn.setFlat(True)
        self._rooms_btn.setCursor(Qt.PointingHandCursor)
        self._rooms_btn.setStyleSheet("color: #89b4fa; text-decoration: underline;")
        self._rooms_btn.clicked.connect(self.rooms_clicked)
        self._rooms_btn.setVisible(False)

        self._separator = QLabel("›")
        self._separator.setVisible(False)

        self._room_label = QLabel("")

        spacer = QWidget()
        spacer.setSizePolicy(
            spacer.sizePolicy().horizontalPolicy(),
            spacer.sizePolicy().verticalPolicy(),
        )
        from PySide6.QtWidgets import QSizePolicy
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._bell_btn = QPushButton("🔔")
        self._bell_btn.setFlat(True)
        self._bell_btn.setFixedSize(36, 36)
        self._bell_btn.clicked.connect(self.notifications_clicked)

        self._settings_btn = QPushButton("⚙")
        self._settings_btn.setFlat(True)
        self._settings_btn.setFixedSize(36, 36)
        self._settings_btn.clicked.connect(self.settings_clicked)

        self._profile_btn = QPushButton("👤")
        self._profile_btn.setFlat(True)
        self._profile_btn.setFixedSize(36, 36)
        self._profile_btn.clicked.connect(self.profile_clicked)

        layout.addWidget(logo)
        layout.addWidget(self._rooms_btn)
        layout.addWidget(self._separator)
        layout.addWidget(self._room_label)
        layout.addWidget(spacer)
        layout.addWidget(self._bell_btn)
        layout.addWidget(self._settings_btn)
        layout.addWidget(self._profile_btn)

    def set_context(self, room_name: str | None = None) -> None:
        in_room = room_name is not None
        self._rooms_btn.setVisible(in_room)
        self._separator.setVisible(in_room)
        self._room_label.setText(room_name or "")

    def set_notification_count(self, count: int) -> None:
        self._bell_btn.setText(f"🔔 {count}" if count > 0 else "🔔")