"""
tools/roadworks/producers.py

Three RoadWorks Canary producers registered at Tool install time.
Registered as room-specific producers via canary_engine.register_producer().
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, List

from core.sdk.types import CanaryOutput


def _get_thresholds(room_id: str) -> dict:
    """Read divergence thresholds from installed_tools.config. Defaults: 15/30."""
    try:
        import json
        from core.db.connection import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT config FROM installed_tools WHERE room_id=? AND tool_id='roadworks'",
                (room_id,),
            ).fetchone()
        cfg = json.loads(row["config"]) if row and row["config"] else {}
        return {
            "amber": cfg.get("divergence_amber", 15),
            "red":   cfg.get("divergence_red", 30),
        }
    except Exception:
        return {"amber": 15, "red": 30}


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
                "SELECT COALESCE(MAX(cumulative_km),0) FROM roadworks_km_progress "
                "WHERE section_id=? AND room_id=?",
                (sid, room_id),
            ).fetchone()
        km_done = cum_row[0] if cum_row else 0
        pct     = round(km_done / length * 100, 1) if length > 0 else 0

        detail_extra = " · QA Approved" if status == "qa_approved" else ""
        outputs.append(CanaryOutput(
            key=f"roadworks.progress.{sid}",
            label=f"{s['label']} Progress",
            value=f"{km_done:.2f} / {length:.1f} km ({pct}%)",
            status=_STATUS_MAP.get(status, "grey"),
            updated_at=now,
            detail=f"Status: {status.replace('_', ' ').title()}{detail_extra}",
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
# Materials producer
# ---------------------------------------------------------------------------

def materials_producer(room_id: str, events: list) -> List[CanaryOutput]:
    from core.db.connection import get_connection
    thresholds = _get_thresholds(room_id)
    now = datetime.utcnow()

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT section_id, material, "
            "SUM(quantity_acquired) AS total_acq, "
            "SUM(quantity_consumed) AS total_con "
            "FROM roadworks_materials WHERE room_id=? "
            "GROUP BY section_id, material",
            (room_id,),
        ).fetchall()

    if not rows:
        return [CanaryOutput(
            key="roadworks.materials.divergence",
            label="Materials Divergence",
            value="No data",
            status="grey",
            updated_at=now,
        )]

    worst = "green"
    details = []
    for r in rows:
        acq = r["total_acq"] or 0
        con = r["total_con"] or 0
        div = round((con - acq) / acq * 100, 1) if acq > 0 else 0

        if div > thresholds["red"]:
            status = "red"
        elif div > thresholds["amber"]:
            status = "amber"
        else:
            status = "green"

        if status == "red" or (status == "amber" and worst != "red"):
            worst = status

        details.append(f"{r['section_id']}/{r['material']}: {div:+.1f}%")

    return [CanaryOutput(
        key="roadworks.materials.divergence",
        label="Materials Divergence",
        value=f"{len([d for d in details if '+' in d and float(d.split(':')[1].strip().rstrip('%')) > thresholds['amber']])} flagged",
        status=worst,
        updated_at=now,
        detail="  ·  ".join(details[:6]),
    )]


# ---------------------------------------------------------------------------
# Activity (check-in) producer
# ---------------------------------------------------------------------------

def rw_activity_producer(room_id: str, events: list) -> List[CanaryOutput]:
    from core.db.connection import get_connection
    now = datetime.utcnow()
    cutoff_24 = (now - timedelta(hours=24)).isoformat()
    cutoff_48 = (now - timedelta(hours=48)).isoformat()

    section_ids = ["S1", "S2", "S3", "S4", "S5", "S6"]

    with get_connection() as conn:
        latest_rows = conn.execute(
            "SELECT pc.entity_id, MAX(se.timestamp) AS last_ts "
            "FROM photo_checkins pc "
            "JOIN sensor_events se ON pc.event_id = se.event_id "
            "WHERE se.room_id=? AND pc.entity_id IN ('S1','S2','S3','S4','S5','S6') "
            "GROUP BY pc.entity_id",
            (room_id,),
        ).fetchall()

    last_checkin = {r["entity_id"]: r["last_ts"] for r in latest_rows}

    stale_24 = [sid for sid in section_ids
                if last_checkin.get(sid, "") < cutoff_24]
    stale_48 = [sid for sid in section_ids
                if last_checkin.get(sid, "") < cutoff_48]

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