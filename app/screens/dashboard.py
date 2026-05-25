"""
Dashboard — default room landing. Scaffold with task summary live.
Canary widget, Workflow widget, Notice Board: placeholder until Days 5–6.
"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from core.models.user import User
from core.sdk.types import RoomId


class _DashWidget(QFrame):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("QFrame { background-color: #181825; border-radius: 8px; }")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 14)

        hdr = QLabel(title)
        hdr.setFont(QFont("", 11, QFont.Bold))
        hdr.setStyleSheet("color: #a6adc8;")
        self._layout.addWidget(hdr)

    def body(self) -> QVBoxLayout:
        return self._layout


class DashboardView(QWidget):
    navigate_to = Signal(str)  # view key to switch to

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: User | None = None
        self._room_id: RoomId | None = None
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        header = QLabel("Dashboard")
        header.setFont(QFont("", 18, QFont.Bold))

        grid = QGridLayout()
        grid.setSpacing(16)

        # Canary status widget
        self._canary_widget = _DashWidget("Canary Status")
        canary_val = QLabel("● Grey — Engine active Day 6")
        canary_val.setStyleSheet("color: #6c7086;")
        self._canary_widget.body().addWidget(canary_val)

        # Task summary widget
        self._task_widget = _DashWidget("Tasks")
        self._task_summary = QLabel("Loading…")
        view_tasks_btn = QPushButton("View all tasks →")
        view_tasks_btn.setFlat(True)
        view_tasks_btn.setStyleSheet("color: #89b4fa; text-align: left;")
        view_tasks_btn.clicked.connect(lambda: self.navigate_to.emit("tasks"))
        self._task_widget.body().addWidget(self._task_summary)
        self._task_widget.body().addWidget(view_tasks_btn)

        # Activity Feed widget
        self._feed_widget = _DashWidget("Recent Activity")
        self._feed_list = QVBoxLayout()
        self._feed_widget.body().addLayout(self._feed_list)
        view_feed_btn = QPushButton("View full feed →")
        view_feed_btn.setFlat(True)
        view_feed_btn.setStyleSheet("color: #89b4fa; text-align: left;")
        view_feed_btn.clicked.connect(lambda: self.navigate_to.emit("activity_feed"))
        self._feed_widget.body().addWidget(view_feed_btn)

        # Notice Board widget
        self._notice_widget = _DashWidget("Notice Board")
        self._notice_list = QVBoxLayout()
        self._notice_widget.body().addLayout(self._notice_list)
        view_nb_btn = QPushButton("View all →")
        view_nb_btn.setFlat(True)
        view_nb_btn.setStyleSheet("color: #89b4fa; text-align: left;")
        view_nb_btn.clicked.connect(lambda: self.navigate_to.emit("notice_board"))
        self._notice_widget.body().addWidget(view_nb_btn)

        # Workflow widget — counts: active and stalled
        self._workflow_widget = _DashWidget("Workflows")
        self._wf_active_label = QLabel("—")
        self._wf_stalled_label = QLabel("—")
        self._workflow_widget.body().addWidget(self._wf_active_label)
        self._workflow_widget.body().addWidget(self._wf_stalled_label)
        view_wf_btn = QPushButton("View all →")
        view_wf_btn.setFlat(True)
        view_wf_btn.setStyleSheet("color: #89b4fa; text-align: left;")
        view_wf_btn.clicked.connect(lambda: self.navigate_to.emit("workflows"))
        self._workflow_widget.body().addWidget(view_wf_btn)

        # Quick actions widget — role-gated
        self._qa_widget = _DashWidget("Quick Actions")
        self._create_task_btn = QPushButton("＋  Create Task")
        self._create_task_btn.setFixedHeight(36)
        self._create_task_btn.clicked.connect(self._on_create_task)
        self._submit_form_btn = QPushButton("⊡  Submit Form")
        self._submit_form_btn.setFixedHeight(36)
        self._submit_form_btn.clicked.connect(lambda: self.navigate_to.emit("sensors"))
        self._qa_widget.body().addWidget(self._create_task_btn)
        self._qa_widget.body().addWidget(self._submit_form_btn)

        grid.addWidget(self._canary_widget,    0, 0)
        grid.addWidget(self._task_widget,      0, 1)
        grid.addWidget(self._feed_widget,      1, 0)
        grid.addWidget(self._notice_widget,    1, 1)
        grid.addWidget(self._workflow_widget,  2, 0)
        grid.addWidget(self._qa_widget,        2, 1)

        layout.addWidget(header)
        layout.addSpacing(12)
        layout.addLayout(grid)
        layout.addStretch()

    def _refresh(self) -> None:
        if not self._actor or not self._room_id:
            return

        # Task summary
        from core.task_impl import task_service
        try:
            counts = task_service.count_by_status(self._actor, self._room_id)
            parts = [f"{counts['active']} active"]
            if counts["overdue"]:
                parts.append(f"<span style='color:#f9e2af'>{counts['overdue']} overdue</span>")
            parts.append(f"{counts['complete']} complete")
            self._task_summary.setText("  ·  ".join(parts))
            self._task_summary.setTextFormat(Qt.RichText)
        except Exception:
            self._task_summary.setText("—")

        # Activity feed preview (last 5 events)
        from core.audit import audit_service
        while self._feed_list.count():
            item = self._feed_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        try:
            events = audit_service.query(self._room_id, self._actor, limit=5)
            if not events:
                self._feed_list.addWidget(QLabel("No activity yet."))
            for ev in events:
                ts = ev["timestamp"][:16].replace("T", " ")
                lbl = QLabel(f"<span style='color:#6c7086'>{ts}</span>  {ev['message']}")
                lbl.setTextFormat(Qt.RichText)
                lbl.setWordWrap(True)
                self._feed_list.addWidget(lbl)
        except Exception:
            self._feed_list.addWidget(QLabel("Could not load activity."))

        # Notice Board preview (top 3)
        while self._notice_list.count():
            item = self._notice_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        try:
            from core.noticeboard_impl import noticeboard_service
            notices = noticeboard_service.list_notices(self._room_id)[:3]
            if not notices:
                self._notice_list.addWidget(QLabel("No notices."))
            for n in notices:
                prefix = "📌 " if n["pinned"] else ""
                lbl = QLabel(f"{prefix}{n['title']}")
                lbl.setWordWrap(True)
                self._notice_list.addWidget(lbl)
        except Exception:
            self._notice_list.addWidget(QLabel("—"))

        # Workflow preview
        while self._wf_list.count():
            item = self._wf_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        try:
            from core.db.connection import get_connection
            with get_connection() as conn:
                rows = conn.execute(
                    "SELECT title, status FROM workflow_instances "
                    "WHERE room_id = ? AND status IN ('active','stalled') "
                    "ORDER BY started_at DESC LIMIT 3",
                    (str(self._room_id),),
                ).fetchall()
            if not rows:
                self._wf_list.addWidget(QLabel("No active workflows."))
            for row in rows:
                colour = "#f9e2af" if row["status"] == "stalled" else "#cdd6f4"
                lbl = QLabel(f"<span style='color:{colour}'>●</span>  {row['title']}")
                lbl.setTextFormat(Qt.RichText)
                lbl.setWordWrap(True)
                self._wf_list.addWidget(lbl)
        except Exception:
            self._wf_list.addWidget(QLabel("—"))

        # Workflow counts (active + stalled)
        try:
            from core.db.connection import get_connection
            with get_connection() as conn:
                n_active = conn.execute(
                    "SELECT COUNT(*) FROM workflow_instances "
                    "WHERE room_id = ? AND status = 'active'",
                    (str(self._room_id),),
                ).fetchone()[0]
                n_stalled = conn.execute(
                    "SELECT COUNT(*) FROM workflow_instances "
                    "WHERE room_id = ? AND status = 'stalled'",
                    (str(self._room_id),),
                ).fetchone()[0]
            self._wf_active_label.setText(f"{n_active} active")
            stalled_text = f"{n_stalled} stalled"
            self._wf_stalled_label.setText(stalled_text)
            colour = "#f9e2af" if n_stalled > 0 else "#6c7086"
            self._wf_stalled_label.setStyleSheet(f"color: {colour};")
        except Exception:
            self._wf_active_label.setText("—")
            self._wf_stalled_label.setText("—")

        # Quick actions — role-gated
        from core.auth.rbac import can_manage_room
        is_officer = can_manage_room(self._actor, self._room_id)
        self._create_task_btn.setVisible(is_officer)
        self._submit_form_btn.setVisible(is_officer)

    def _on_create_task(self) -> None:
        """Open the task creation dialog from the dashboard."""
        from app.screens.tasks_view import _CreateTaskDialog
        from core.room_impl import RoomAPIImpl
        members = RoomAPIImpl(self._actor).list_members(self._room_id)
        dlg = _CreateTaskDialog(members, self)
        if dlg.exec() != dlg.Accepted:
            return
        vals = dlg.values()
        try:
            from core.task_impl import task_service
            task_service.create_task(
                actor=self._actor,
                room_id=self._room_id,
                title=vals["title"],
                description=vals["description"],
                assigned_to=vals["assigned_to"],
                due_at=vals["due_at"],
                trackability=vals["trackability"],
            )
            self._refresh()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", str(exc))