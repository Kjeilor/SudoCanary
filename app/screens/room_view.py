"""
app/screens/room_view.py

Room view — top-level container for a single room.
Left: RoomSidebar. Right: QStackedWidget with all room views.

Day 4: Workflows, Sensors, Documents, Notice Board are live.
       notice_count_changed signal drives the top bar bell badge.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QWidget

from core.auth.rbac import get_room_role
from core.models.user import User
from core.room_impl import RoomAPIImpl
from core.sdk.types import RoomId

from app.widgets.sidebar import RoomSidebar
from app.screens.dashboard import DashboardView
from app.screens.tasks_view import TasksView
from app.screens.activity_feed_view import ActivityFeedView
from app.screens.workflows import WorkflowsView
from app.screens.sensors import SensorsView
from app.screens.documents import DocumentsView
from app.screens.noticeboard import NoticeBoardView
from app.screens.placeholder_view import PlaceholderView

_VIEWS = {
    "dashboard":    0,
    "tasks":        1,
    "activity_feed": 2,
    "workflows":    3,
    "sensors":      4,
    "documents":    5,
    "notice_board": 6,
    "reports":      7,
}


class RoomView(QWidget):
    status_message      = Signal(str)
    notice_count_changed = Signal(int)   # → top bar bell badge

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

        self._dashboard   = DashboardView()
        self._tasks_view  = TasksView()
        self._feed_view   = ActivityFeedView()
        self._wf_view     = WorkflowsView()
        self._sensor_view = SensorsView()
        self._doc_view    = DocumentsView()
        self._nb_view     = NoticeBoardView()

        self._stack.addWidget(self._dashboard)                          # 0
        self._stack.addWidget(self._tasks_view)                         # 1
        self._stack.addWidget(self._feed_view)                          # 2
        self._stack.addWidget(self._wf_view)                            # 3
        self._stack.addWidget(self._sensor_view)                        # 4
        self._stack.addWidget(self._doc_view)                           # 5
        self._stack.addWidget(self._nb_view)                            # 6
        self._stack.addWidget(PlaceholderView("Reports", "Day 11"))     # 7

        # Signal forwarding
        self._dashboard.navigate_to.connect(self._navigate)
        self._tasks_view.status_message.connect(self.status_message)
        self._wf_view.status_message.connect(self.status_message)
        self._sensor_view.status_message.connect(self.status_message)
        self._doc_view.status_message.connect(self.status_message)
        self._nb_view.status_message.connect(self.status_message)
        self._nb_view.notice_count_changed.connect(self.notice_count_changed)

        layout.addWidget(self._sidebar)
        layout.addWidget(self._stack, stretch=1)

    def load_room(self, actor: User, room_id: str, room_name: str) -> None:
        self._actor = actor
        self._room_id = RoomId(room_id)

        members = RoomAPIImpl(actor).list_members(self._room_id)
        member_count = len(members)
        role = get_room_role(actor, self._room_id)

        self._sidebar.set_room(room_name, role, member_count)
        self._sidebar.set_active("dashboard")

        # Load all live views
        self._dashboard.load(actor, self._room_id)
        self._tasks_view.load(actor, self._room_id, members)
        self._feed_view.load(actor, self._room_id)
        self._wf_view.load(actor, self._room_id)
        self._sensor_view.load(actor, self._room_id)
        self._doc_view.load(actor, self._room_id)
        self._nb_view.load(actor, self._room_id)

        self._stack.setCurrentIndex(_VIEWS["dashboard"])
        self.status_message.emit("Dashboard loaded")

    def _navigate(self, key: str) -> None:
        idx = _VIEWS.get(key, 0)
        self._stack.setCurrentIndex(idx)
        self._sidebar.set_active(key)
        self.status_message.emit(f"{key.replace('_', ' ').title()} loaded")

        # Refresh on navigation
        if key == "activity_feed":
            self._feed_view.load(self._actor, self._room_id)
        elif key == "tasks":
            members = RoomAPIImpl(self._actor).list_members(self._room_id)
            self._tasks_view.load(self._actor, self._room_id, members)
        elif key == "workflows":
            self._wf_view.load(self._actor, self._room_id)
        elif key == "sensors":
            self._sensor_view.load(self._actor, self._room_id)
        elif key == "documents":
            self._doc_view.load(self._actor, self._room_id)
        elif key == "notice_board":
            self._nb_view.load(self._actor, self._room_id)