"""
tools/roadworks/producers.py — Day 10

Three RoadWorks Canary producers.

Materials producer now outputs per-section outputs (roadworks.materials.S1..S6)
and a summary (roadworks.materials.summary). Thresholds read from
installed_tools.config. Divergence status drives dashed map overlay.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List

from core.sdk.types import CanaryOutput


def _get_config(room_id: str) -> dict:
    try:
        from core.db.connection import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT config FROM installed_tools WHERE room_id=? AND tool_id='roadworks'",
                (room_id,),
            ).fetchone()
        return json.loads(row["config"]) if row and row["config"] else {}
    except Exception:
        return {}


def _divergence_status(pct: float, amber: float, red: float) -> str:
    if pct >= red:
        return "red"
    if pct >= amber:
        return "amber"
    return "green"


# ---------------------------------------------------------------------------
# Progress producer
# ---------------------------------------------------------------------------

def progress_producer(room_id: str, events: list) -> List[CanaryOutput]:
    from core.db.connection import get_connection
    now = datetime.utcnow()
    outputs = []

    with get_connection() as conn:
        sections = conn.execute(
            "SELECT * FROM roadworks_sections WHERE room_id=? ORDER BY section_id",
            (room_id,),
        ).fetchall()

    if not sections:
        return [CanaryOutput(
            key="roadworks.progress.summary",
            label="Road Progress",
            value="No sections configured",
            status="grey",
            updated_at=now,
        )]

    _STATUS_MAP = {
        "not_started": "grey",
        "in_progress":  "amber",
        "complete":     "green",
        "qa_approved":  "green",
    }
    counts = {"not_started": 0, "in_progress": 0, "complete": 0, "qa_approved": 0}

    for s in sections:
        sid    = s["section_id"]
        status = s["status"]
        length = s["length_km"]
        counts[status] = counts.get(status, 0) + 1

        with get_connection() as conn:
            cum_row = conn.execute(
                "SELECT COALESCE(MAX(cumulative_km), 0) FROM roadworks_km_progress "
                "WHERE section_id=? AND room_id=?",
                (sid, room_id),
            ).fetchone()
        km_done = cum_row[0] if cum_row else 0
        pct = round(km_done / length * 100, 1) if length > 0 else 0

        detail_extra = " · QA Approved" if status == "qa_approved" else ""
        outputs.append(CanaryOutput(
            key=f"roadworks.progress.{sid}",
            label=f"{s['label']} Progress",
            value=f"{km_done:.2f} / {length:.1f} km ({pct}%)",
            status=_STATUS_MAP.get(status, "grey"),
            updated_at=now,
            detail=f"Status: {status.replace('_',' ').title()}{detail_extra}",
        ))

    all_approved = all(s["status"] == "qa_approved" for s in sections)
    any_in_prog  = any(s["status"] == "in_progress" for s in sections)
    summary_status = "green" if all_approved else ("amber" if any_in_prog else "grey")

    outputs.append(CanaryOutput(
        key="roadworks.progress.summary",
        label="Overall Progress",
        value=(
            f"{counts['qa_approved']} QA'd  ·  "
            f"{counts['complete']} complete  ·  "
            f"{counts['in_progress']} in progress  ·  "
            f"{counts['not_started']} not started"
        ),
        status=summary_status,
        updated_at=now,
    ))
    return outputs


# ---------------------------------------------------------------------------
# Materials producer — per-section per-material outputs
# ---------------------------------------------------------------------------

def materials_producer(room_id: str, events: list) -> List[CanaryOutput]:
    from core.db.connection import get_connection
    cfg = _get_config(room_id)
    amber_thresh = cfg.get("divergence_amber", 15.0)
    red_thresh   = cfg.get("divergence_red",   30.0)
    now = datetime.utcnow()

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT section_id, material, unit, "
            "SUM(quantity_acquired) AS total_acq, "
            "SUM(quantity_consumed) AS total_con "
            "FROM roadworks_materials WHERE room_id=? "
            "GROUP BY section_id, material, unit",
            (room_id,),
        ).fetchall()

    if not rows:
        return [CanaryOutput(
            key="roadworks.materials.summary",
            label="Materials Divergence",
            value="No data",
            status="grey",
            updated_at=now,
        )]

    # Group by section — pick worst material per section
    by_section: dict[str, dict] = {}
    for r in rows:
        sid  = r["section_id"]
        acq  = r["total_acq"] or 0
        con  = r["total_con"] or 0
        div  = round((con - acq) / acq * 100, 1) if acq > 0 else 0
        stat = _divergence_status(div, amber_thresh, red_thresh)

        if sid not in by_section or abs(div) > abs(by_section[sid]["divergence_pct"]):
            by_section[sid] = {
                "material":       r["material"],
                "acquired":       acq,
                "consumed":       con,
                "unit":           r["unit"],
                "divergence_pct": div,
                "status":         stat,
            }

    outputs = []
    worst_div   = 0.0
    sections_flagged = 0
    worst_section = ""

    for sid, d in sorted(by_section.items()):
        stat = d["status"]
        div  = d["divergence_pct"]
        if stat in ("amber", "red"):
            sections_flagged += 1
        if abs(div) > abs(worst_div):
            worst_div    = div
            worst_section = sid

        detail = (
            f"Consumed {div:+.1f}% {'more' if div > 0 else 'less'} "
            f"{d['material']} than acquired. "
            f"Threshold: {red_thresh:.0f}%. "
            f"Review procurement records."
        ) if abs(div) > amber_thresh else None

        outputs.append(CanaryOutput(
            key=f"roadworks.materials.{sid}",
            label=f"Section {sid} — Materials",
            value=json.dumps({
                "material":       d["material"],
                "acquired":       d["acquired"],
                "consumed":       d["consumed"],
                "divergence_pct": d["divergence_pct"],
                "unit":           d["unit"],
            }),
            status=stat,
            updated_at=now,
            detail=detail,
        ))

    overall_status = "green"
    for o in outputs:
        if o.status == "red":
            overall_status = "red"; break
        if o.status == "amber":
            overall_status = "amber"

    summary_detail = (
        f"Section {worst_section} {by_section[worst_section]['material']} "
        f"divergence exceeds threshold."
    ) if worst_section and sections_flagged else "All materials within threshold."

    outputs.append(CanaryOutput(
        key="roadworks.materials.summary",
        label="Materials Divergence",
        value=json.dumps({
            "sections_flagged":    sections_flagged,
            "worst_divergence_pct": worst_div,
        }),
        status=overall_status,
        updated_at=now,
        detail=summary_detail,
    ))
    return outputs


# ---------------------------------------------------------------------------
# Activity (check-in) producer
# ---------------------------------------------------------------------------

def rw_activity_producer(room_id: str, events: list) -> List[CanaryOutput]:
    from core.db.connection import get_connection
    now = datetime.utcnow()
    cutoff_24 = (now - timedelta(hours=24)).isoformat()
    cutoff_48 = (now - timedelta(hours=48)).isoformat()

    with get_connection() as conn:
        section_rows = conn.execute(
            "SELECT section_id FROM roadworks_sections WHERE room_id=? ORDER BY section_id",
            (room_id,),
        ).fetchall()
        section_ids = [r["section_id"] for r in section_rows] or ["S1","S2","S3","S4","S5","S6"]

        latest_rows = conn.execute(
            "SELECT pc.entity_id, MAX(se.timestamp) AS last_ts "
            "FROM photo_checkins pc "
            "JOIN sensor_events se ON pc.event_id = se.event_id "
            "WHERE se.room_id=? "
            "GROUP BY pc.entity_id",
            (room_id,),
        ).fetchall()

    last_checkin = {r["entity_id"]: r["last_ts"] for r in latest_rows}

    stale_24 = [sid for sid in section_ids if last_checkin.get(sid, "") < cutoff_24]
    stale_48 = [sid for sid in section_ids if last_checkin.get(sid, "") < cutoff_48]

    checkin_status = "green" if not stale_24 else ("amber" if not stale_48 else "red")
    stale_status   = "green" if not stale_48 else ("amber" if len(stale_48) <= 2 else "red")

    return [
        CanaryOutput(
            key="roadworks.activity.checkins",
            label="Site Check-ins (24h)",
            value=f"{len(section_ids) - len(stale_24)} / {len(section_ids)} sections",
            status=checkin_status,
            updated_at=now,
            detail=f"No check-in (24h): {', '.join(stale_24) or 'none'}",
        ),
        CanaryOutput(
            key="roadworks.activity.stale_sections",
            label="Stale Sections (48h+)",
            value=str(len(stale_48)),
            status=stale_status,
            updated_at=now,
            detail=f"Stale sections: {', '.join(stale_48) or 'none'}",
        ),
    ]