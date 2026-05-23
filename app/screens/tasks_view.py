"""
Tasks tab — live.
Table: title, assigned to, status (with OVERDUE highlighted), due date.
Create task dialog (Officer only). Click row to update status.
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget, QCheckBox, QMessageBox,
)

from core.auth.rbac import can_manage_room
from core.models.user import RoomRole, User
from core.sdk.types import RoomId, Task, TaskId, TaskStatus, TaskTrackability, UserId
from core.task_impl import task_service

_STATUS_COLOUR = {
    TaskStatus.OPEN:        "#cdd6f4",
    TaskStatus.IN_PROGRESS: "#89b4fa",
    TaskStatus.COMPLETE:    "#a6e3a1",
    TaskStatus.CANCELLED:   "#6c7086",
    TaskStatus.OVERDUE:     "#f9e2af",
}

_STATUS_LABEL = {
    TaskStatus.OPEN:        "Open",
    TaskStatus.IN_PROGRESS: "In Progress",
    TaskStatus.COMPLETE:    "Complete",
    TaskStatus.CANCELLED:   "Cancelled",
    TaskStatus.OVERDUE:     "Overdue",
}

_NEXT_STATUS = {
    TaskStatus.OPEN:        [TaskStatus.IN_PROGRESS, TaskStatus.COMPLETE, TaskStatus.CANCELLED],
    TaskStatus.IN_PROGRESS: [TaskStatus.COMPLETE, TaskStatus.CANCELLED],
    TaskStatus.OVERDUE:     [TaskStatus.IN_PROGRESS, TaskStatus.COMPLETE, TaskStatus.CANCELLED],
    TaskStatus.COMPLETE:    [],
    TaskStatus.CANCELLED:   [],
}


class _CreateTaskDialog(QDialog):
    def __init__(self, members: List[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Task")
        self.setMinimumWidth(420)
        self._members = members
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self._title = QLineEdit()
        self._title.setPlaceholderText("Required")
        self._description = QTextEdit()
        self._description.setFixedHeight(80)
        self._description.setPlaceholderText("Optional")

        self._assignee = QComboBox()
        self._assignee.addItem("Unassigned", None)
        for m in self._members:
            self._assignee.addItem(m["display_name"], m["user_id"])

        self._due = QDateTimeEdit()
        self._due.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._due.setCalendarPopup(True)
        self._due.setDateTime(datetime.now().replace(second=0, microsecond=0))
        self._has_due = QCheckBox("Set due date")
        self._has_due.stateChanged.connect(lambda s: self._due.setEnabled(s == Qt.Checked))
        self._due.setEnabled(False)

        self._trackable = QCheckBox("Trackable (feeds Canary)")
        self._trackable.setChecked(True)

        form.addRow("Title *", self._title)
        form.addRow("Description", self._description)
        form.addRow("Assign to", self._assignee)
        form.addRow("", self._has_due)
        form.addRow("Due date", self._due)
        form.addRow("", self._trackable)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        if not self._title.text().strip():
            QMessageBox.warning(self, "Required", "Title is required.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "title":       self._title.text().strip(),
            "description": self._description.toPlainText().strip(),
            "assigned_to": self._assignee.currentData(),
            "due_at":      (
                self._due.dateTime().toPython()
                if self._has_due.isChecked() else None
            ),
            "trackability": (
                TaskTrackability.TRACKABLE
                if self._trackable.isChecked()
                else TaskTrackability.UNTRACKABLE
            ),
        }


class _UpdateStatusDialog(QDialog):
    def __init__(self, task: Task, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update Task")
        self.setMinimumWidth(360)
        self._task = task
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"<b>{self._task.title}</b>"))
        layout.addWidget(QLabel(f"Current status: {_STATUS_LABEL[self._task.status]}"))
        layout.addSpacing(8)

        next_statuses = _NEXT_STATUS.get(self._task.status, [])
        if not next_statuses:
            layout.addWidget(QLabel("This task is terminal — no further transitions."))
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            self._selected_status = None
            return

        layout.addWidget(QLabel("Move to:"))
        self._status_combo = QComboBox()
        for s in next_statuses:
            self._status_combo.addItem(_STATUS_LABEL[s], s)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(self._status_combo)
        layout.addWidget(buttons)

    def selected_status(self) -> TaskStatus | None:
        if hasattr(self, "_status_combo"):
            return self._status_combo.currentData()
        return None


class TasksView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: User | None = None
        self._room_id: RoomId | None = None
        self._members: List[dict] = []
        self._tasks: List[Task] = []
        self._build_ui()

    def load(self, actor: User, room_id: RoomId, members: List[dict]) -> None:
        self._actor = actor
        self._room_id = room_id
        self._members = members
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        # Toolbar
        toolbar = QHBoxLayout()
        header = QLabel("Tasks")
        header.setFont(QFont("", 16, QFont.Bold))

        self._create_btn = QPushButton("+ Create Task")
        self._create_btn.setFixedHeight(34)
        self._create_btn.clicked.connect(self._create_task)

        toolbar.addWidget(header)
        toolbar.addStretch()
        toolbar.addWidget(self._create_btn)

        # Table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Title", "Assigned To", "Status", "Due Date", "Trackable"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().hide()
        self._table.cellDoubleClicked.connect(self._on_row_double_clicked)

        self._empty_label = QLabel("No tasks yet. Create one to get started.")
        self._empty_label.setStyleSheet("color: #6c7086;")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.hide()

        layout.addLayout(toolbar)
        layout.addSpacing(8)
        layout.addWidget(self._table)
        layout.addWidget(self._empty_label)

    def _refresh(self) -> None:
        if not self._actor or not self._room_id:
            return
        self._tasks = task_service.list_tasks(self._actor, self._room_id)
        self._table.setRowCount(0)

        officer = can_manage_room(self._actor, self._room_id)
        self._create_btn.setVisible(officer)

        if not self._tasks:
            self._empty_label.show()
            self._table.hide()
            return

        self._empty_label.hide()
        self._table.show()

        # Build member lookup
        member_map = {m["user_id"]: m["display_name"] for m in self._members}

        for task in self._tasks:
            row = self._table.rowCount()
            self._table.insertRow(row)

            title_item = QTableWidgetItem(task.title)
            if task.parent_task_id:
                title_item.setText(f"↳ {task.title}")

            assignee = member_map.get(task.assigned_to, "Unassigned") if task.assigned_to else "Unassigned"
            status_label = _STATUS_LABEL[task.status]
            due = task.due_at.strftime("%Y-%m-%d %H:%M") if task.due_at else "—"
            trackable = "Yes" if task.trackability == TaskTrackability.TRACKABLE else "No"

            items = [
                title_item,
                QTableWidgetItem(assignee),
                QTableWidgetItem(status_label),
                QTableWidgetItem(due),
                QTableWidgetItem(trackable),
            ]

            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                if task.status == TaskStatus.OVERDUE:
                    item.setForeground(QColor(_STATUS_COLOUR[TaskStatus.OVERDUE]))
                elif col == 2:
                    item.setForeground(QColor(_STATUS_COLOUR.get(task.status, "#cdd6f4")))
                self._table.setItem(row, col, item)

        self.status_message.emit(f"{len(self._tasks)} task{'s' if len(self._tasks) != 1 else ''} loaded")

    def _create_task(self) -> None:
        dlg = _CreateTaskDialog(self._members, self)
        if dlg.exec() != QDialog.Accepted:
            return
        vals = dlg.values()
        try:
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
            self.status_message.emit("Task created")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _on_row_double_clicked(self, row: int, _col: int) -> None:
        if row >= len(self._tasks):
            return
        task = self._tasks[row]
        dlg = _UpdateStatusDialog(task, self)
        if dlg.exec() != QDialog.Accepted:
            return
        new_status = dlg.selected_status()
        if not new_status:
            return
        try:
            task_service.update_task_status(
                self._actor, self._room_id, task.task_id, new_status
            )
            self._refresh()
            self.status_message.emit(f"Task moved to {_STATUS_LABEL[new_status]}")
        except ValueError as e:
            QMessageBox.warning(self, "Not Allowed", str(e))