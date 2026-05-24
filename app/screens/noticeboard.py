"""
app/screens/noticeboard.py

Notice Board — wired to noticeboard_service.

All room members see all active notices, pinned first.
Officer and above can post. Admin can pin/unpin.
"Remove after" date is optional — expired notices are hidden, not deleted.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from core.auth.rbac import can_manage_room, can_post_notice, is_admin
from core.models.user import User
from core.noticeboard_impl import noticeboard_service
from core.sdk.types import RoomId


# ---------------------------------------------------------------------------
# Post notice dialog
# ---------------------------------------------------------------------------

class _PostNoticeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Post Notice")
        self.setMinimumWidth(440)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("Notice title")

        self._body_input = QTextEdit()
        self._body_input.setFixedHeight(120)
        self._body_input.setPlaceholderText("Notice body")

        self._pinned = QCheckBox("Pin this notice")

        self._has_expiry = QCheckBox("Remove after:")
        self._expiry_date = QDateEdit()
        self._expiry_date.setCalendarPopup(True)
        self._expiry_date.setDisplayFormat("yyyy-MM-dd")
        from PySide6.QtCore import QDate
        self._expiry_date.setDate(QDate.currentDate().addDays(7))
        self._expiry_date.setEnabled(False)
        self._has_expiry.stateChanged.connect(
            lambda s: self._expiry_date.setEnabled(s == Qt.Checked)
        )

        expiry_row = QHBoxLayout()
        expiry_row.addWidget(self._has_expiry)
        expiry_row.addWidget(self._expiry_date)
        expiry_row.addStretch()

        form.addRow("Title *", self._title_input)
        form.addRow("Body *", self._body_input)
        form.addRow("", self._pinned)
        form.addRow("Expiry", expiry_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        if not self._title_input.text().strip():
            QMessageBox.warning(self, "Required", "Title is required.")
            return
        if not self._body_input.toPlainText().strip():
            QMessageBox.warning(self, "Required", "Body is required.")
            return
        self.accept()

    def values(self) -> dict:
        expires_at = None
        if self._has_expiry.isChecked():
            d = self._expiry_date.date()
            expires_at = datetime(d.year(), d.month(), d.day(), 23, 59, 59)
        return {
            "title":      self._title_input.text().strip(),
            "body":       self._body_input.toPlainText().strip(),
            "pinned":     self._pinned.isChecked(),
            "expires_at": expires_at,
        }


# ---------------------------------------------------------------------------
# Notice card widget
# ---------------------------------------------------------------------------

class _NoticeCard(QFrame):
    pin_toggled = Signal(str, bool)  # notice_id, pinned

    def __init__(self, notice: dict, can_pin: bool, parent=None) -> None:
        super().__init__(parent)
        self._notice = notice
        self.setStyleSheet(
            "QFrame { background-color: #181825; border-radius: 8px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        title_row = QHBoxLayout()
        title = QLabel(notice["title"])
        title.setFont(QFont("", 12, QFont.Bold))
        title.setWordWrap(True)

        badges = QHBoxLayout()
        if notice["pinned"]:
            pin_lbl = QLabel("📌 Pinned")
            pin_lbl.setStyleSheet("color: #f9e2af;")
            badges.addWidget(pin_lbl)

        if notice.get("expires_at"):
            exp_lbl = QLabel(f"Expires {notice['expires_at'][:10]}")
            exp_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
            badges.addWidget(exp_lbl)

        badges.addStretch()

        if can_pin:
            pin_btn_label = "Unpin" if notice["pinned"] else "Pin"
            pin_btn = QPushButton(pin_btn_label)
            pin_btn.setFixedHeight(26)
            pin_btn.setFixedWidth(60)
            notice_id = notice["notice_id"]
            pinned_now = notice["pinned"]
            pin_btn.clicked.connect(
                lambda: self.pin_toggled.emit(notice_id, not pinned_now)
            )
            badges.addWidget(pin_btn)

        title_row.addWidget(title, stretch=1)

        body = QLabel(notice["body"])
        body.setWordWrap(True)
        body.setStyleSheet("color: #a6adc8;")

        ts = notice["created_at"][:16].replace("T", " ")
        meta = QLabel(f"Posted {ts}")
        meta.setStyleSheet("color: #6c7086; font-size: 11px;")

        layout.addLayout(title_row)
        layout.addLayout(badges)
        layout.addWidget(body)
        layout.addWidget(meta)


# ---------------------------------------------------------------------------
# Notice Board screen
# ---------------------------------------------------------------------------

class NoticeBoardView(QWidget):
    status_message = Signal(str)
    notice_count_changed = Signal(int)  # drives bell badge

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: Optional[User] = None
        self._room_id: Optional[RoomId] = None
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        officer = can_post_notice(actor, room_id)
        self._post_btn.setVisible(officer)
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        toolbar = QHBoxLayout()
        header = QLabel("Notice Board")
        header.setFont(QFont("", 16, QFont.Bold))

        self._post_btn = QPushButton("+ Post Notice")
        self._post_btn.setFixedHeight(34)
        self._post_btn.setVisible(False)
        self._post_btn.clicked.connect(self._post_notice)

        toolbar.addWidget(header)
        toolbar.addStretch()
        toolbar.addWidget(self._post_btn)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.NoFrame)

        self._cards_widget = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setSpacing(10)
        self._cards_layout.setAlignment(Qt.AlignTop)
        self._scroll_area.setWidget(self._cards_widget)

        self._empty_label = QLabel("No notices have been posted.")
        self._empty_label.setStyleSheet("color: #6c7086;")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.hide()

        layout.addLayout(toolbar)
        layout.addSpacing(8)
        layout.addWidget(self._scroll_area, stretch=1)
        layout.addWidget(self._empty_label)

    def _refresh(self) -> None:
        # Clear existing cards
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        notices = noticeboard_service.list_notices(self._room_id)

        if not notices:
            self._empty_label.show()
            self._scroll_area.hide()
            self.notice_count_changed.emit(0)
            self.status_message.emit("No notices")
            return

        self._empty_label.hide()
        self._scroll_area.show()

        can_pin = is_admin(self._actor) or can_manage_room(self._actor, self._room_id)

        for notice in notices:
            card = _NoticeCard(notice, can_pin)
            card.pin_toggled.connect(self._on_pin_toggled)
            self._cards_layout.addWidget(card)

        count = len(notices)
        self.notice_count_changed.emit(count)
        self.status_message.emit(f"{count} notice{'s' if count != 1 else ''}")

    def _post_notice(self) -> None:
        dlg = _PostNoticeDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        vals = dlg.values()
        try:
            noticeboard_service.post_notice(
                actor=self._actor,
                room_id=self._room_id,
                title=vals["title"],
                body=vals["body"],
                expires_at=vals["expires_at"],
                pinned=vals["pinned"],
            )
            self._refresh()
            self.status_message.emit("Notice posted")
            top = self.window()
            if hasattr(top, "_banner_bar"):
                top._banner_bar.show_banner("Notice posted successfully.", kind="success")
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _on_pin_toggled(self, notice_id: str, pinned: bool) -> None:
        try:
            noticeboard_service.pin_notice(
                self._actor, self._room_id, notice_id, pinned
            )
            self._refresh()
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))