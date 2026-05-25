"""
app/screens/member_directory.py

Member directory tab.

Table: display name | role | last active (from audit_log) | task count
Admin: "Remove" per row, "Add Member" button at top with live username search.
Non-admin: read-only list.
Click a row: detail panel (name, system role, room role, tasks assigned).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.auth.rbac import can_manage_room, is_admin
from core.db.connection import get_connection
from core.models.user import RoomRole, User
from core.room_impl import RoomAPIImpl
from core.sdk.types import RoomId, UserId


def _last_active(user_id: str, room_id: str) -> str:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT timestamp FROM audit_log "
            "WHERE user_id = ? AND resource = ? "
            "ORDER BY seq DESC LIMIT 1",
            (user_id, room_id),
        ).fetchone()
    return row["timestamp"][:16].replace("T", " ") if row else "Never"


def _task_count(user_id: str, room_id: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM tasks "
            "WHERE assigned_to = ? AND room_id = ? AND status NOT IN ('complete','cancelled')",
            (user_id, room_id),
        ).fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Add member dialog — live search
# ---------------------------------------------------------------------------

class _AddMemberDialog(QDialog):
    def __init__(self, room_id: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Member")
        self.setMinimumWidth(400)
        self._room_id = room_id
        self._results: List[dict] = []
        self._selected_user: Optional[dict] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Type username to search…")
        self._search_input.textChanged.connect(self._search)

        self._results_list = QTableWidget(0, 2)
        self._results_list.setHorizontalHeaderLabels(["Username", "Display name"])
        self._results_list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._results_list.setEditTriggers(QTableWidget.NoEditTriggers)
        self._results_list.setSelectionBehavior(QTableWidget.SelectRows)
        self._results_list.verticalHeader().hide()
        self._results_list.setFixedHeight(160)
        self._results_list.currentRowChanged.connect(self._on_select)

        self._role_combo = QComboBox()
        self._role_combo.addItem("Officer", RoomRole.OFFICER)
        self._role_combo.addItem("Viewer", RoomRole.VIEWER)

        form.addRow("Search user", self._search_input)
        form.addRow("Results", self._results_list)
        form.addRow("Role", self._role_combo)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self._buttons.accepted.connect(self._validate)
        self._buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(self._buttons)

    def _search(self, text: str) -> None:
        self._results_list.setRowCount(0)
        self._selected_user = None
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        if len(text) < 1:
            return

        with get_connection() as conn:
            # Exclude users already in the room
            rows = conn.execute(
                "SELECT user_id, username, display_name FROM users "
                "WHERE username LIKE ? AND is_active = 1 "
                "AND user_id NOT IN "
                "  (SELECT user_id FROM room_roles WHERE room_id = ?) "
                "LIMIT 10",
                (f"%{text}%", self._room_id),
            ).fetchall()

        self._results = [dict(r) for r in rows]
        for r in self._results:
            row = self._results_list.rowCount()
            self._results_list.insertRow(row)
            self._results_list.setItem(row, 0, QTableWidgetItem(r["username"]))
            self._results_list.setItem(row, 1, QTableWidgetItem(r["display_name"]))

    def _on_select(self, row: int) -> None:
        if 0 <= row < len(self._results):
            self._selected_user = self._results[row]
            self._buttons.button(QDialogButtonBox.Ok).setEnabled(True)
        else:
            self._selected_user = None
            self._buttons.button(QDialogButtonBox.Ok).setEnabled(False)

    def _validate(self) -> None:
        if not self._selected_user:
            QMessageBox.warning(self, "Required", "Select a user from the results.")
            return
        self.accept()

    def selected_user_id(self) -> Optional[str]:
        return self._selected_user["user_id"] if self._selected_user else None

    def selected_role(self) -> RoomRole:
        return self._role_combo.currentData()


# ---------------------------------------------------------------------------
# Member directory screen
# ---------------------------------------------------------------------------

class MemberDirectoryView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: Optional[User] = None
        self._room_id: Optional[RoomId] = None
        self._members: List[dict] = []
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        is_officer = can_manage_room(actor, room_id)
        self._add_btn.setVisible(is_officer)
        self._refresh()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Left — member table
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(20, 16, 8, 16)

        toolbar = QHBoxLayout()
        header = QLabel("Directory")
        header.setFont(QFont("", 16, QFont.Bold))

        self._add_btn = QPushButton("+ Add Member")
        self._add_btn.setFixedHeight(34)
        self._add_btn.setVisible(False)
        self._add_btn.clicked.connect(self._add_member)

        toolbar.addWidget(header)
        toolbar.addStretch()
        toolbar.addWidget(self._add_btn)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Role", "Last Active", "Open Tasks"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.verticalHeader().hide()
        self._table.setAlternatingRowColors(True)
        self._table.currentCellChanged.connect(lambda cur_row, cur_col, prev_row, prev_col: self._on_row_selected(cur_row))

        ll.addLayout(toolbar)
        ll.addWidget(self._table)

        # Right — detail panel
        right = QFrame()
        right.setFixedWidth(260)
        right.setStyleSheet("QFrame { background-color: #181825; }")
        self._detail_layout = QVBoxLayout(right)
        self._detail_layout.setContentsMargins(16, 16, 16, 16)
        self._detail_placeholder = QLabel("Select a member\nto see details.")
        self._detail_placeholder.setStyleSheet("color: #6c7086;")
        self._detail_placeholder.setAlignment(Qt.AlignCenter)
        self._detail_layout.addWidget(self._detail_placeholder)
        self._detail_layout.addStretch()

        layout.addWidget(left, stretch=1)
        layout.addWidget(right)

    def _refresh(self) -> None:
        self._table.setRowCount(0)
        self._members = list(RoomAPIImpl(self._actor).list_members(self._room_id))
        is_officer = can_manage_room(self._actor, self._room_id)

        for m in self._members:
            r = self._table.rowCount()
            self._table.insertRow(r)
            self._table.setItem(r, 0, QTableWidgetItem(m["display_name"]))
            role_label = "Officer" if m["role"] == "officer" else "Viewer"
            self._table.setItem(r, 1, QTableWidgetItem(role_label))
            self._table.setItem(r, 2, QTableWidgetItem(
                _last_active(m["user_id"], str(self._room_id))
            ))
            tc = _task_count(m["user_id"], str(self._room_id))
            self._table.setItem(r, 3, QTableWidgetItem(str(tc) if tc else "—"))

            if is_officer:
                remove_btn = QPushButton("Remove")
                remove_btn.setFixedHeight(26)
                uid = m["user_id"]
                remove_btn.clicked.connect(lambda _, u=uid: self._remove_member(u))
                self._table.setCellWidget(r, 3, remove_btn)  # replaces task count

        self.status_message.emit(f"{len(self._members)} member(s)")

    def _on_row_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._members):
            return
        m = self._members[row]
        self._show_detail(m)

    def _show_detail(self, m: dict) -> None:
        # Clear detail panel
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        name = QLabel(m["display_name"])
        name.setFont(QFont("", 13, QFont.Bold))
        name.setWordWrap(True)

        role_label = "Officer" if m["role"] == "officer" else "Viewer"
        role = QLabel(f"Room role: {role_label}")
        role.setStyleSheet("color: #a6adc8;")

        last = QLabel(f"Last active: {_last_active(m['user_id'], str(self._room_id))}")
        last.setStyleSheet("color: #a6adc8;")

        tc = _task_count(m["user_id"], str(self._room_id))
        tasks = QLabel(f"Open tasks: {tc}")
        tasks.setStyleSheet("color: #a6adc8;")

        self._detail_layout.addWidget(name)
        self._detail_layout.addSpacing(8)
        self._detail_layout.addWidget(role)
        self._detail_layout.addWidget(last)
        self._detail_layout.addWidget(tasks)
        self._detail_layout.addStretch()

    def _add_member(self) -> None:
        dlg = _AddMemberDialog(str(self._room_id), self)
        if dlg.exec() != QDialog.Accepted:
            return
        user_id = dlg.selected_user_id()
        role = dlg.selected_role()
        if not user_id:
            return
        try:
            RoomAPIImpl(self._actor).add_member(
                self._room_id, UserId(user_id), role
            )
            self._refresh()
            self.status_message.emit("Member added")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _remove_member(self, user_id: str) -> None:
        confirm = QMessageBox.question(
            self, "Remove member",
            "Remove this member from the room?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            RoomAPIImpl(self._actor).remove_member(
                self._room_id, UserId(user_id)
            )
            self._refresh()
            self.status_message.emit("Member removed")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))