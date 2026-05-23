"""
Room view — top-level container for a single room.
Left: RoomSidebar. Right: QStackedWidget with all room views.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QWidget

from core.models.user import User
from core.room_impl import RoomAPIImpl
from core.sdk.types import RoomId

from app.widgets.sidebar import RoomSidebar
from app.screens.dashboard import DashboardView
from app.screens.tasks_view import TasksView
from app.screens.activity_feed_view import ActivityFeedView
from app.screens.placeholder_view import PlaceholderView

_VIEWS = {
    "dashboard":    0,
    "tasks":        1,
    "activity_feed": 2,
    "workflows":    3,
    "sensors":      4,
    "documents":    5,
    "reports":      6,
}


class RoomView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: User | None = None
        self._room_id: RoomId | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._sidebar = RoomSidebar()
        self._sidebar.nav_requested.connect(self._navigate)

        self._stack = QStackedWidget()

        self._dashboard = DashboardView()
        self._tasks_view = TasksView()
        self._feed_view = ActivityFeedView()

        self._stack.addWidget(self._dashboard)                              # 0
        self._stack.addWidget(self._tasks_view)                             # 1
        self._stack.addWidget(self._feed_view)                              # 2
        self._stack.addWidget(PlaceholderView("Workflows", "Day 4"))        # 3
        self._stack.addWidget(PlaceholderView("Sensors", "Day 5"))          # 4
        self._stack.addWidget(PlaceholderView("Documents", "Day 5"))        # 5
        self._stack.addWidget(PlaceholderView("Reports", "Day 11"))         # 6

        self._dashboard.navigate_to.connect(self._navigate)
        self._tasks_view.status_message.connect(self.status_message)

        layout.addWidget(self._sidebar)
        layout.addWidget(self._stack, stretch=1)

    def load_room(self, actor: User, room_id: str, room_name: str) -> None:
        self._actor = actor
        self._room_id = RoomId(room_id)

        members = RoomAPIImpl(actor).list_members(self._room_id)
        member_count = len(members)

        from core.auth.rbac import get_room_role
        role = get_room_role(actor, self._room_id)

        self._sidebar.set_room(room_name, role, member_count)
        self._sidebar.set_active("dashboard")

        self._dashboard.load(actor, self._room_id)
        self._tasks_view.load(actor, self._room_id, members)
        self._feed_view.load(actor, self._room_id)

        self._stack.setCurrentIndex(_VIEWS["dashboard"])
        self.status_message.emit("Dashboard loaded")

    def _navigate(self, key: str) -> None:
        idx = _VIEWS.get(key, 0)
        self._stack.setCurrentIndex(idx)
        self._sidebar.set_active(key)
        self.status_message.emit(f"{key.replace('_', ' ').title()} loaded")

        # Refresh live views on navigation
        if key == "activity_feed":
            self._feed_view.load(self._actor, self._room_id)
        elif key == "tasks":
            members = RoomAPIImpl(self._actor).list_members(self._room_id)
            self._tasks_view.load(self._actor, self._room_id, members)