"""
app/screens/reports.py — Days 11/12

Three reports + data export + data retention panel.

Reports:
  1. Project Status Report  (PDF)
  2. Audit Trail Report     (PDF)
  3. Materials Divergence   (PDF)

Exports: sensor_events, tasks, audit_trail → CSV

Retention: view eligibility, configure period, purge (Admin only)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from core.db.connection import get_connection
from core.db.retention import retention_service
from core.export.data_export import data_exporter
from core.models.user import User
from core.sdk.types import RoomId


class ReportsView(QWidget):
    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._actor: Optional[User] = None
        self._room_id: Optional[RoomId] = None
        self._build_ui()

    def load(self, actor: User, room_id: RoomId) -> None:
        self._actor = actor
        self._room_id = room_id
        self._refresh_retention()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Reports & Data")
        title.setFont(QFont("", 18, QFont.Bold))
        layout.addWidget(title)
        layout.addSpacing(8)

        tabs = QTabWidget()
        tabs.addTab(self._build_reports_tab(), "Reports")
        tabs.addTab(self._build_export_tab(),  "Export Data")
        tabs.addTab(self._build_retention_tab(), "Retention")
        layout.addWidget(tabs, stretch=1)

    # ── Reports tab ──────────────────────────────────────────────────────────

    def _build_reports_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        for title, desc, handler in [
            (
                "📋  Project Status Report",
                "Overall Canary status, section progress, alerts, workflows, QA approvals.",
                self._gen_status_report,
            ),
            (
                "📋  Audit Trail Report",
                "Complete event log with action summary. Filtered by date and type.",
                self._gen_audit_report,
            ),
            (
                "📋  Materials Divergence Report",
                "Per-section materials acquired vs consumed. Flags sections above threshold.",
                self._gen_materials_report,
            ),
        ]:
            card = self._report_card(title, desc, handler)
            layout.addWidget(card)

        layout.addStretch()
        return w

    def _report_card(self, title: str, desc: str, handler) -> QFrame:
        card = QFrame()
        card.setStyleSheet("QFrame { background: #2E2E2E; border-radius: 8px; }")
        card.setFixedHeight(100)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 14)

        name_lbl = QLabel(title)
        name_lbl.setFont(QFont("", 12, QFont.Bold))
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet("color: #AAAAAA;")
        desc_lbl.setWordWrap(True)

        btn = QPushButton("Generate PDF")
        btn.setFixedWidth(130)
        btn.setFixedHeight(30)
        btn.clicked.connect(handler)

        row = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(name_lbl)
        left.addWidget(desc_lbl)
        row.addLayout(left, stretch=1)
        row.addWidget(btn, alignment=Qt.AlignRight | Qt.AlignVCenter)
        cl.addLayout(row)
        return card

    # ── Export tab ───────────────────────────────────────────────────────────

    def _build_export_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)

        group = QGroupBox("Export Data")
        gl = QVBoxLayout(group)

        for label, handler in [
            ("Sensor Events", self._export_sensors),
            ("Tasks",         self._export_tasks),
            ("Audit Trail",   self._export_audit),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            btn = QPushButton("Export CSV")
            btn.setFixedWidth(110)
            btn.setFixedHeight(28)
            btn.clicked.connect(handler)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(btn)
            gl.addLayout(row)

        layout.addWidget(group)

        self._export_log = QLabel("No recent exports.")
        self._export_log.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        self._export_log.setWordWrap(True)
        layout.addWidget(QLabel("Recent exports:", styleSheet="font-weight: bold;"))
        layout.addWidget(self._export_log)
        layout.addStretch()
        return w

    # ── Retention tab ─────────────────────────────────────────────────────────

    def _build_retention_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)

        group = QGroupBox("Data Retention")
        gl = QFormLayout(group)

        self._retention_spin = QSpinBox()
        self._retention_spin.setRange(365, 3650)
        self._retention_spin.setValue(1095)
        self._retention_spin.setSuffix(" days")
        gl.addRow("Retention period", self._retention_spin)

        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(80)
        save_btn.clicked.connect(self._save_retention)
        gl.addRow("", save_btn)

        layout.addWidget(group)

        eligible_group = QGroupBox("Records eligible for deletion")
        el = QVBoxLayout(eligible_group)
        self._sensor_eligible  = QLabel("—")
        self._audit_eligible   = QLabel("—")
        self._doc_eligible     = QLabel("—")
        self._cutoff_lbl       = QLabel("")
        self._cutoff_lbl.setStyleSheet("color: #AAAAAA; font-size: 12px;")
        el.addWidget(QLabel("Sensor events:"))
        el.addWidget(self._sensor_eligible)
        el.addWidget(QLabel("Audit entries:"))
        el.addWidget(self._audit_eligible)
        el.addWidget(QLabel("Documents:"))
        el.addWidget(self._doc_eligible)
        el.addWidget(self._cutoff_lbl)

        btn_row = QHBoxLayout()
        preview_btn = QPushButton("Preview eligible records")
        preview_btn.setFixedHeight(30)
        preview_btn.clicked.connect(self._refresh_retention)
        self._purge_btn = QPushButton("Purge expired records")
        self._purge_btn.setFixedHeight(30)
        self._purge_btn.setStyleSheet("color: #EF4444;")
        self._purge_btn.clicked.connect(self._purge)
        btn_row.addWidget(preview_btn)
        btn_row.addWidget(self._purge_btn)
        btn_row.addStretch()

        layout.addWidget(eligible_group)
        layout.addLayout(btn_row)
        layout.addStretch()
        return w

    def _refresh_retention(self) -> None:
        if not self._room_id:
            return
        days = retention_service.get_retention_days(self._room_id)
        self._retention_spin.setValue(days)
        eligible = retention_service.get_eligible_for_deletion(self._room_id)
        self._sensor_eligible.setText(str(eligible["sensor_events"]))
        self._audit_eligible.setText(str(eligible["audit_log"]))
        self._doc_eligible.setText(str(eligible["documents"]))
        self._cutoff_lbl.setText(f"Cutoff: records before {eligible['cutoff_date']}")

    def _save_retention(self) -> None:
        if not self._room_id or not self._actor:
            return
        try:
            retention_service.set_retention_days(
                self._room_id, self._retention_spin.value(),
                self._actor.user_id,
            )
            self._refresh_retention()
            self.status_message.emit("Retention policy updated")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid", str(exc))

    def _purge(self) -> None:
        if not self._room_id or not self._actor:
            return
        eligible = retention_service.get_eligible_for_deletion(self._room_id)
        total = sum(v for k, v in eligible.items() if k not in ("cutoff_date", "retention_days"))
        if total == 0:
            QMessageBox.information(self, "Nothing to purge", "No records are eligible for deletion.")
            return

        dlg = _ConfirmPurgeDialog(eligible, self)
        if dlg.exec() != QDialog.Accepted:
            return
        deleted = retention_service.purge_expired(self._room_id, self._actor.user_id)
        self._refresh_retention()
        msg = f"Purged: {deleted['sensor_events']} events, {deleted['audit_log']} audit entries, {deleted['documents']} documents."
        QMessageBox.information(self, "Purge complete", msg)
        self.status_message.emit("Data purged")

    # ── Export handlers ──────────────────────────────────────────────────────

    def _export_sensors(self) -> None:
        try:
            path = data_exporter.export_sensor_events(
                self._room_id, None, None, None, self._actor.user_id
            )
            self._show_export(path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _export_tasks(self) -> None:
        try:
            path = data_exporter.export_tasks(self._room_id, self._actor.user_id)
            self._show_export(path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _export_audit(self) -> None:
        try:
            path = data_exporter.export_audit_trail(self._room_id, self._actor.user_id)
            self._show_export(path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _show_export(self, path: str) -> None:
        name = Path(path).name
        self._export_log.setText(f"✓  {name}")
        self.status_message.emit(f"Exported: {name}")
        self._open_file(Path(path).parent)

    # ── PDF report generators ─────────────────────────────────────────────────

    def _gen_status_report(self) -> None:
        if not self._room_id:
            return
        try:
            data = self._collect_status_data()
            path = self._write_status_pdf(data)
            self.status_message.emit(f"Report: {path.name}")
            self._open_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Report error", str(exc))

    def _gen_audit_report(self) -> None:
        if not self._room_id:
            return
        try:
            path = self._write_audit_pdf()
            self.status_message.emit(f"Report: {path.name}")
            self._open_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Report error", str(exc))

    def _gen_materials_report(self) -> None:
        if not self._room_id:
            return
        try:
            path = self._write_materials_pdf()
            self.status_message.emit(f"Report: {path.name}")
            self._open_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Report error", str(exc))

    # ── Data collection ───────────────────────────────────────────────────────

    def _collect_status_data(self) -> dict:
        from core.canary_engine import canary_engine, _overall_status
        rid = str(self._room_id)

        state = canary_engine.get_latest_state(self._room_id)
        if state is None:
            state = canary_engine.compute(self._room_id)

        with get_connection() as conn:
            sections = conn.execute(
                "SELECT s.section_id, s.label, s.status, s.length_km, "
                "COALESCE(MAX(k.cumulative_km), 0) AS km_done "
                "FROM roadworks_sections s "
                "LEFT JOIN roadworks_km_progress k "
                "  ON k.section_id=s.section_id AND k.room_id=s.room_id "
                "WHERE s.room_id=? GROUP BY s.section_id ORDER BY s.section_id",
                (rid,),
            ).fetchall()

            wf_active  = conn.execute("SELECT COUNT(*) FROM workflow_instances WHERE room_id=? AND status='active'",  (rid,)).fetchone()[0]
            wf_stalled = conn.execute("SELECT COUNT(*) FROM workflow_instances WHERE room_id=? AND status='stalled'", (rid,)).fetchone()[0]
            tasks_open = conn.execute("SELECT COUNT(*) FROM tasks WHERE room_id=? AND status IN ('open','in_progress')", (rid,)).fetchone()[0]
            tasks_over = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE room_id=? AND status IN ('open','in_progress') AND due_at < ?",
                (rid, datetime.utcnow().isoformat()),
            ).fetchone()[0]

        alerts = []
        for o in state.outputs:
            if o.status in ("amber", "red") and o.key.startswith("roadworks."):
                alerts.append({"key": o.key, "label": o.label, "status": o.status, "detail": o.detail})

        return {
            "overall_status": _overall_status(list(state.outputs)).upper(),
            "generated_at":   datetime.utcnow().strftime("%d %b %Y %H:%M"),
            "sections":       [dict(s) for s in sections],
            "alerts":         alerts,
            "wf_active":      wf_active, "wf_stalled": wf_stalled,
            "tasks_open":     tasks_open, "tasks_overdue": tasks_over,
            "qa_approved":    [s["section_id"] for s in sections if s["status"] == "qa_approved"],
            "qa_pending":     [s["section_id"] for s in sections if s["status"] != "qa_approved"],
        }

    # ── PDF writers ───────────────────────────────────────────────────────────

    def _pdf_path(self, name: str) -> Path:
        out = Path("data/reports") / str(self._room_id)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return out / f"{name}_{ts}.pdf"

    def _write_status_pdf(self, data: dict) -> Path:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm

        path = self._pdf_path("status_report")
        doc  = SimpleDocTemplate(str(path), pagesize=A4,
                                 rightMargin=2*cm, leftMargin=2*cm,
                                 topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        S = {"green": "#29AB87", "amber": "#F59E0B", "red": "#EF4444", "grey": "#6B7280"}
        sc = S.get(data["overall_status"].lower(), "#6B7280")
        story = [
            Paragraph("<b>ROAD RECONSTRUCTION PROJECT</b>", styles["Heading1"]),
            Paragraph(f"Status Report — Generated: {data['generated_at']}", styles["Normal"]),
            Spacer(1, 0.3*cm),
            Paragraph(f"<b>OVERALL STATUS:</b>  <font color='{sc}'>{data['overall_status']}</font>", styles["Normal"]),
            Spacer(1, 0.5*cm),
            Paragraph("SECTION PROGRESS", styles["Heading2"]),
        ]

        tbl_data = [["Section", "Status", "KM Done", "Total", "%"]]
        for s in data["sections"]:
            pct = int(s["km_done"] / s["length_km"] * 100) if s["length_km"] else 0
            tbl_data.append([s["section_id"], s["status"].replace("_"," ").title(),
                              f"{s['km_done']:.1f}", f"{s['length_km']:.1f}", f"{pct}%"])

        tbl = Table(tbl_data, colWidths=[2*cm, 4*cm, 2.5*cm, 2.5*cm, 2*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#383838")),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1),
             [colors.HexColor("#2E2E2E"), colors.HexColor("#262626")]),
            ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#444444")),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("PADDING",  (0,0), (-1,-1), 4),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.4*cm))

        if data["alerts"]:
            story.append(Paragraph("ALERTS", styles["Heading2"]))
            for a in data["alerts"]:
                icon = "🔴" if a["status"] == "red" else "🟡"
                story.append(Paragraph(f"{icon}  {a['label']} — {a.get('detail','')}", styles["Normal"]))
            story.append(Spacer(1, 0.3*cm))

        story += [
            Paragraph("WORKFLOW STATUS", styles["Heading2"]),
            Paragraph(f"Active: {data['wf_active']}  ·  Stalled: {data['wf_stalled']}", styles["Normal"]),
            Spacer(1, 0.2*cm),
            Paragraph("TASKS", styles["Heading2"]),
            Paragraph(f"Open: {data['tasks_open']}  ·  Overdue: {data['tasks_overdue']}", styles["Normal"]),
            Spacer(1, 0.2*cm),
            Paragraph("QA APPROVALS", styles["Heading2"]),
            Paragraph(f"Approved: {', '.join(data['qa_approved']) or 'None'}  ·  "
                      f"Pending: {', '.join(data['qa_pending']) or 'None'}", styles["Normal"]),
        ]
        doc.build(story)
        return path

    def _write_audit_pdf(self) -> Path:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm

        rid  = str(self._room_id)
        path = self._pdf_path("audit_trail_report")
        doc  = SimpleDocTemplate(str(path), pagesize=A4,
                                 rightMargin=1.5*cm, leftMargin=1.5*cm,
                                 topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT timestamp, username, action, details, success "
                "FROM audit_log WHERE resource=? ORDER BY timestamp DESC LIMIT 500",
                (rid,),
            ).fetchall()

        action_counts: dict[str, int] = {}
        for r in rows:
            action_counts[r["action"]] = action_counts.get(r["action"], 0) + 1

        now = datetime.utcnow().strftime("%d %b %Y %H:%M")
        story = [
            Paragraph("<b>AUDIT TRAIL REPORT</b>", styles["Heading1"]),
            Paragraph(f"Generated: {now}  ·  Total events: {len(rows)}", styles["Normal"]),
            Spacer(1, 0.4*cm),
            Paragraph("SUMMARY BY ACTION TYPE", styles["Heading2"]),
        ]

        for action, count in sorted(action_counts.items(), key=lambda x: -x[1])[:10]:
            story.append(Paragraph(f"  {action}: {count}", styles["Normal"]))

        story.append(Spacer(1, 0.4*cm))
        story.append(Paragraph("DETAIL LOG (latest 100 events)", styles["Heading2"]))

        tbl_data = [["Timestamp", "User", "Action", "Status"]]
        for r in rows[:100]:
            tbl_data.append([
                r["timestamp"][:16].replace("T", " "),
                r["username"] or "—",
                r["action"],
                "✓" if r["success"] else "✗",
            ])

        tbl = Table(tbl_data, colWidths=[4*cm, 3*cm, 7*cm, 1.5*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#383838")),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1),
             [colors.HexColor("#2E2E2E"), colors.HexColor("#262626")]),
            ("GRID",    (0,0), (-1,-1), 0.25, colors.HexColor("#444444")),
            ("FONTSIZE",(0,0), (-1,-1), 8),
            ("PADDING", (0,0), (-1,-1), 3),
        ]))
        story.append(tbl)
        doc.build(story)
        return path

    def _write_materials_pdf(self) -> Path:
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm

        rid  = str(self._room_id)
        path = self._pdf_path("materials_divergence_report")
        doc  = SimpleDocTemplate(str(path), pagesize=A4,
                                 rightMargin=1.5*cm, leftMargin=1.5*cm,
                                 topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT section_id, material, SUM(quantity_acquired) AS acq, "
                "SUM(quantity_consumed) AS con, unit "
                "FROM roadworks_materials WHERE room_id=? "
                "GROUP BY section_id, material, unit ORDER BY section_id",
                (rid,),
            ).fetchall()

            cfg_row = conn.execute(
                "SELECT config FROM installed_tools WHERE room_id=? AND tool_id='roadworks'",
                (rid,),
            ).fetchone()

        cfg        = json.loads(cfg_row["config"]) if cfg_row and cfg_row["config"] else {}
        amber_t    = cfg.get("divergence_amber", 15)
        red_t      = cfg.get("divergence_red", 30)
        now        = datetime.utcnow().strftime("%d %b %Y %H:%M")

        story = [
            Paragraph("<b>MATERIALS DIVERGENCE REPORT</b>", styles["Heading1"]),
            Paragraph(f"Generated: {now}", styles["Normal"]),
            Spacer(1, 0.4*cm),
            Paragraph("SECTION SUMMARY", styles["Heading2"]),
        ]

        tbl_data = [["Section", "Material", "Acquired", "Consumed", "Divergence", "Status"]]
        flagged  = []

        for r in rows:
            acq = r["acq"] or 0
            con = r["con"] or 0
            div = round((con - acq) / acq * 100, 1) if acq > 0 else 0

            if div >= red_t:
                status = "🔴 EXCEEDS THRESHOLD"
                flagged.append(dict(r) | {"div": div})
            elif div >= amber_t:
                status = "🟡 APPROACHING"
            else:
                status = "✅ Within threshold"

            tbl_data.append([r["section_id"], r["material"].title(),
                              f"{acq:.0f}{r['unit']}", f"{con:.0f}{r['unit']}",
                              f"{div:+.1f}%", status])

        tbl = Table(tbl_data, colWidths=[1.5*cm, 3*cm, 3*cm, 3*cm, 2.5*cm, 4*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#383838")),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0,1), (-1,-1),
             [colors.HexColor("#2E2E2E"), colors.HexColor("#262626")]),
            ("GRID",    (0,0), (-1,-1), 0.25, colors.HexColor("#444444")),
            ("FONTSIZE",(0,0), (-1,-1), 8),
            ("PADDING", (0,0), (-1,-1), 3),
        ]))
        story.append(tbl)

        if flagged:
            story.append(Spacer(1, 0.4*cm))
            story.append(Paragraph("FLAGGED SECTIONS", styles["Heading2"]))
            for f in flagged:
                acq = f["acq"] or 0
                con = f["con"] or 0
                story.append(Paragraph(
                    f"<b>{f['section_id']} — {f['material'].title()} divergence {f['div']:+.1f}%</b><br/>"
                    f"Acquired: {acq:.0f} {f['unit']}. Consumed: {con:.0f} {f['unit']}. "
                    f"Difference: {con-acq:.0f} {f['unit']}.<br/>"
                    f"Recommend: review procurement records and site consumption logs.",
                    styles["Normal"],
                ))
                story.append(Spacer(1, 0.2*cm))

        story += [
            Spacer(1, 0.3*cm),
            Paragraph("THRESHOLD CONFIGURATION", styles["Heading2"]),
            Paragraph(f"Amber threshold: {amber_t}%  ·  Red threshold: {red_t}%", styles["Normal"]),
        ]
        doc.build(story)
        return path

    @staticmethod
    def _open_file(path) -> None:
        try:
            p = str(path)
            if sys.platform == "darwin":
                subprocess.run(["open", p])
            elif sys.platform == "win32":
                os.startfile(p)
            else:
                subprocess.run(["xdg-open", p])
        except Exception:
            pass


class _ConfirmPurgeDialog(QDialog):
    def __init__(self, eligible: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm Purge")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>This will permanently delete:</b><br/>"
            f"  {eligible['sensor_events']} sensor events<br/>"
            f"  {eligible['audit_log']} audit entries<br/>"
            f"  {eligible['documents']} documents<br/><br/>"
            f"Records before: {eligible['cutoff_date']}<br/><br/>"
            f"<b>This action cannot be undone.</b><br/>"
            f"Type CONFIRM to proceed:",
            textFormat=Qt.RichText,
        ))
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type CONFIRM")
        layout.addWidget(self._input)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Purge")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_accept(self) -> None:
        if self._input.text().strip() == "CONFIRM":
            self.accept()
        else:
            QMessageBox.warning(self, "Required", "Type CONFIRM to proceed.")