"""
app/screens/workflows.py — Day 6 full implementation.

Left panel: instance list sorted stalled-first.
Right panel: step progress chain, current step detail, step history,
             Advance button (Officer+), Cancel button (Admin only).
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QFrame,
)

from core.auth.rbac import can_manage_room, is_admin, require_officer
from core.models.user import User
from core.sdk.types import RoomId
from core.workflows.workflow_impl import workflow_service

_STATUS_COLOUR = {
    "active":    "#89b4fa",
    "stalled":   "#f9e2af",
    "complete":  "#a6e3a1",
    "cancelled": "#6c7086",
}
_STATUS_BG = {
    "stalled": "rgba(249, 226, 175, 0.08)",
}


# ---------------------------------------------------------------------------
# Advance dialog
# ---------------------------------------------------------------------------

class _AdvanceDialog(QDialog):
    def __init__(self, step_label: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Advance Step")
        self.setMinimumWidth(380)
        self._build_ui(step_label)

    def _build_ui(self, step_label: str) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        layout.addWidget(QLabel(f"Advancing: <b>{step_label}</b>"))
        layout.addSpacing(8)

        self._notes = QLineEdit()
        self._notes.setPlaceholderText("Optional notes on this advancement")
        form.addRow("Notes", self._notes)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Advance →")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(buttons)

    def notes(self) -> str:
        return self._notes.text().strip()


# ---------------------------------------------------------------------------
# Step progress widget
# ---------------------------------------------------------------------------

class _StepChain(QWidget):
    def __init__(self, steps: List[dict], current_step_id: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        completed_ids = set()
        found_current = False

        for i, step in enumerate(steps):
            sid = step["step_id"]
            is_current = sid == current_step_id
            is_done = not found_current and not is_current
            if is_current:
                found_current = True

            # Step box
            box = QLabel(step["label"])
            box.setAlignment(Qt.AlignCenter)
            box.setWordWrap(True)
            box.setFixedHeight(48)
            box.setContentsMargins(8, 4, 8, 4)

            if is_done:
                box.setStyleSheet(
                    "background:#1e3a1e; color:#a6e3a1; border-radius:4px;"
                )
            elif is_current:
                box.setStyleSheet(
                    "background:#1e2a5e; color:#89b4fa; border-radius:4px; "
                    "border:1px solid #89b4fa;"
                )
            else:
                box.setStyleSheet(
                    "background:#181825; color:#6c7086; border-radius:4px;"
                )

            layout.addWidget(box, stretch=1)

            if i < len(steps) - 1:
                arrow = QLabel("→")
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setStyleSheet("color: #45475a; font-size: 16px;")
                arrow.setFixedWidth(20)
                layout.addWidget(arrow)


# ---------------------------------------------------------------------------
# Workflows screen
# ---------------------------------------------------------------------------

class WorkflowsView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: Optional[User] = None
        self._room_id: Optional[RoomId] = None
        self._instances: List[dict] = []
        self._selected: Optional[dict] = None
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        self._refresh()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        # ── Left: instance list ───────────────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(300)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(12, 12, 8, 12)

        header = QLabel("Workflows")
        header.setFont(QFont("", 13, QFont.Bold))

        refresh_btn = QPushButton("↻")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setFlat(True)
        refresh_btn.clicked.connect(self._refresh)

        hrow = QHBoxLayout()
        hrow.addWidget(header)
        hrow.addStretch()
        hrow.addWidget(refresh_btn)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_instance_selected)

        self._empty_label = QLabel(
            "No workflows configured.\n"
            "An Admin can add workflow templates."
        )
        self._empty_label.setStyleSheet("color: #6c7086;")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.hide()

        ll.addLayout(hrow)
        ll.addWidget(self._list)
        ll.addWidget(self._empty_label)

        # ── Right: instance detail ────────────────────────────────────────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)

        self._right = QWidget()
        self._right_layout = QVBoxLayout(self._right)
        self._right_layout.setContentsMargins(16, 12, 16, 12)
        self._right_layout.setAlignment(Qt.AlignTop)
        self._right_layout.addWidget(
            QLabel("Select a workflow instance.", styleSheet="color:#6c7086;")
        )
        right_scroll.setWidget(self._right)

        splitter.addWidget(left)
        splitter.addWidget(right_scroll)
        splitter.setSizes([300, 700])
        layout.addWidget(splitter)

    # ── Instance list ─────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._list.clear()
        self._instances = workflow_service.list_instances(self._actor, self._room_id)

        if not self._instances:
            self._empty_label.show()
            self._list.hide()
            self.status_message.emit("No workflows")
            return

        self._empty_label.hide()
        self._list.show()

        for inst in self._instances:
            status = inst["status"]
            colour = _STATUS_COLOUR.get(status, "#cdd6f4")
            started = inst["started_at"][:10]
            item = QListWidgetItem(
                f"{inst['title']}\n"
                f"{inst['current_step_label']}  ·  {started}"
            )
            if status == "stalled":
                item.setForeground(QColor("#f9e2af"))
                item.setBackground(QColor(249, 226, 175, 20))
            elif status == "complete":
                item.setForeground(QColor("#a6e3a1"))
            self._list.addItem(item)

        n_stalled = sum(1 for i in self._instances if i["status"] == "stalled")
        msg = f"{len(self._instances)} workflow(s)"
        if n_stalled:
            msg += f"  ·  {n_stalled} stalled"
        self.status_message.emit(msg)

    def _on_instance_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._instances):
            return
        inst_summary = self._instances[row]
        try:
            self._selected = workflow_service.get_instance(inst_summary["instance_id"])
        except Exception as exc:
            self._selected = inst_summary
        self._render_detail()

    # ── Detail panel ──────────────────────────────────────────────────────────

    def _render_detail(self) -> None:
        inst = self._selected
        if not inst:
            return

        while self._right_layout.count():
            item = self._right_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Title + status
        title = QLabel(inst["title"])
        title.setFont(QFont("", 15, QFont.Bold))
        title.setWordWrap(True)

        status = inst["status"]
        status_lbl = QLabel(status.upper())
        colour = _STATUS_COLOUR.get(status, "#cdd6f4")
        status_lbl.setStyleSheet(f"color: {colour}; font-weight: bold;")

        title_row = QHBoxLayout()
        title_row.addWidget(title, stretch=1)
        title_row.addWidget(status_lbl)

        # Step chain
        steps = inst.get("all_steps", [])
        if steps:
            chain = _StepChain(steps, inst["current_step_id"])
            chain_group = QGroupBox("Step Progress")
            cgl = QVBoxLayout(chain_group)
            cgl.addWidget(chain)
        else:
            chain_group = QLabel("Step definitions not found.")
            chain_group.setStyleSheet("color:#6c7086;")

        # Current step detail
        step_def = inst.get("current_step_def") or {}
        step_group = QGroupBox("Current Step")
        sgl = QFormLayout(step_group)
        sgl.addRow("Step", QLabel(inst.get("current_step_label", "—")))
        sgl.addRow("Description", QLabel(step_def.get("description", "—")))
        sgl.addRow("Required role", QLabel(
            step_def.get("required_role", "Any").replace("_", " ").title()
        ))
        sla = workflow_service.get_sla_remaining(inst)
        if sla:
            sla_lbl = QLabel(sla)
            if "Overdue" in sla:
                sla_lbl.setStyleSheet("color: #f38ba8; font-weight: bold;")
            else:
                sla_lbl.setStyleSheet("color: #a6adc8;")
            sgl.addRow("SLA", sla_lbl)

        # Step history
        history = inst.get("step_history", [])
        hist_group = QGroupBox("Step History")
        hgl = QVBoxLayout(hist_group)
        if not history:
            hgl.addWidget(QLabel("No steps advanced yet.", styleSheet="color:#6c7086;"))
        else:
            table = QTableWidget(len(history), 4)
            table.setHorizontalHeaderLabels(["Step", "Advanced by", "Date", "Notes"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.verticalHeader().hide()
            table.setMaximumHeight(160)
            for r, h in enumerate(history):
                table.setItem(r, 0, QTableWidgetItem(h["step_id"]))
                table.setItem(r, 1, QTableWidgetItem(h.get("advancer_name") or h["advanced_by"]))
                table.setItem(r, 2, QTableWidgetItem(h["advanced_at"][:16].replace("T", " ")))
                table.setItem(r, 3, QTableWidgetItem(h.get("notes") or "—"))
            hgl.addWidget(table)

        # Action buttons
        btn_row = QHBoxLayout()
        is_officer = can_manage_room(self._actor, self._room_id)
        is_admin_user = is_admin(self._actor)
        is_terminal = status in ("complete", "cancelled")

        if is_officer and not is_terminal:
            advance_btn = QPushButton("Advance →")
            advance_btn.setFixedHeight(36)
            advance_btn.clicked.connect(self._on_advance)
            btn_row.addWidget(advance_btn)

        if is_admin_user and not is_terminal:
            cancel_btn = QPushButton("Cancel Instance")
            cancel_btn.setFixedHeight(36)
            cancel_btn.setStyleSheet("color: #f38ba8;")
            cancel_btn.clicked.connect(self._on_cancel)
            btn_row.addWidget(cancel_btn)

        btn_row.addStretch()

        self._right_layout.addLayout(title_row)
        self._right_layout.addWidget(chain_group)
        self._right_layout.addWidget(step_group)
        self._right_layout.addWidget(hist_group)
        self._right_layout.addLayout(btn_row)
        self._right_layout.addStretch()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_advance(self) -> None:
        if not self._selected:
            return
        step_label = self._selected.get("current_step_label", "current step")
        dlg = _AdvanceDialog(step_label, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            updated = workflow_service.advance_step(
                self._actor, self._selected["instance_id"], dlg.notes()
            )
            self._selected = updated
            self._refresh()
            # Re-select same instance
            for i, inst in enumerate(self._instances):
                if inst["instance_id"] == updated["instance_id"]:
                    self._list.setCurrentRow(i)
                    break
            self.status_message.emit("Step advanced")
            from core.canary_engine import canary_engine
            canary_engine.compute(self._room_id)
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _on_cancel(self) -> None:
        if not self._selected:
            return
        reason, ok = __import__('PySide6.QtWidgets', fromlist=['QInputDialog']).QInputDialog.getText(
            self, "Cancel Workflow", "Reason for cancellation (required):"
        )
        if not ok or not reason.strip():
            return
        try:
            workflow_service.cancel_instance(self._actor, self._selected["instance_id"], reason)
            self._selected = None
            self._refresh()
            self.status_message.emit("Workflow cancelled")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))