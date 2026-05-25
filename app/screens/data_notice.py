"""
DPPA 2019 S.13 — Data subject must be informed before or at the time
personal data is collected. Shown only on first login. User must
actively check the box; the Continue button is disabled until they do.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
    QScrollArea, QCheckBox, QFrame,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont

from core.auth.auth_service import auth_service

_NOTICE_HTML = """
<h2 style="margin-top:0">Data Privacy Notice</h2>
<p>This notice is provided under the
<b>Data Protection and Privacy Act, 2019 (DPPA)</b> — Uganda, Section 13.</p>

<h3>Data Controller</h3>
<p>Sudo Canary is operated by your organisation. All data is stored
locally on this device and is never transmitted over any network.</p>

<h3>Data Collected</h3>
<ul>
  <li>Your username and display name</li>
  <li>Your activity within rooms you are assigned to</li>
  <li>Audit logs of actions taken within the system</li>
  <li>Timestamps of login and session events</li>
</ul>

<h3>Purpose</h3>
<p>Data is collected for institutional monitoring, evaluation, and
accountability as defined by your organisation's mandate.</p>

<h3>Protection Measures</h3>
<p>All data is encrypted at rest using AES-256 (SQLCipher). Access is
controlled by role-based permissions. No internet connection is required
or used at any point.</p>

<h3>Your Rights (DPPA S.20–S.29)</h3>
<p>You have the right to access your personal data, request corrections,
and lodge complaints with the <b>Personal Data Protection Office of Uganda</b>
(PDPO). Contact your system administrator to exercise these rights.</p>

<h3>Retention</h3>
<p>Data retention periods are set by your organisation administrator.
You may request deletion by contacting your administrator.</p>
"""


class DataNoticeScreen(QWidget):
    notice_accepted = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._user = None
        self._build_ui()

    def set_user(self, user) -> None:
        self._user = user
        self._check.setChecked(False)
        self._continue_btn.setEnabled(False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 48, 80, 40)
        layout.setSpacing(16)

        header = QLabel("Privacy & Data Notice")
        header.setFont(QFont("", 20, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QLabel(_NOTICE_HTML)
        content.setWordWrap(True)
        content.setTextFormat(Qt.RichText)
        content.setAlignment(Qt.AlignTop)
        content.setContentsMargins(24, 24, 24, 24)
        scroll.setWidget(content)

        self._check = QCheckBox(
            "I have read and understood this data privacy notice."
        )
        self._check.stateChanged.connect(
           lambda state: self._continue_btn.setEnabled(state == 2)
        )

        self._continue_btn = QPushButton("Continue")
        self._continue_btn.setFixedHeight(42)
        self._continue_btn.setEnabled(False)
        self._continue_btn.clicked.connect(self._accept)

        layout.addWidget(header)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(self._check)
        layout.addWidget(self._continue_btn)

    def _accept(self) -> None:
        if self._user:
            auth_service.mark_data_notice_accepted(self._user.user_id)
        self.notice_accepted.emit()