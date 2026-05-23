"""
Append-only audit trail service.

append()          — the only write path into audit_log
query()           — the only read path, role-filtered
verify_integrity() — checks seq for deletions (gap = deleted row)
format_event()    — translates ActionType + detail dict into plain English

Role filtering (using Day 2 RoomRole model):
  VIEWER  → own events only
  OFFICER → all room activity
  ADMIN   → everything including member/permission changes
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from core.db.connection import get_connection
from core.models.user import RoomRole, User
from core.sdk.types import ActionType, RoomId, UserId


# ---------------------------------------------------------------------------
# Plain-English event formatter
# ---------------------------------------------------------------------------

_FMT: Dict[str, callable] = {
    ActionType.TASK_CREATED:            lambda d, u: f"{u} created task: {d.get('title', '?')}",
    ActionType.TASK_ASSIGNED:           lambda d, u: f"{u} assigned task to {d.get('assignee_name') or d.get('assigned_to', '?')}",
    ActionType.TASK_PROGRESSED:         lambda d, u: f"{u} moved \"{d.get('title', '?')}\" to {d.get('new_status', '?').replace('_', ' ')}",
    ActionType.TASK_COMPLETED:          lambda d, u: f"{u} completed: {d.get('title', '?')}",
    ActionType.TASK_CONTINUED:          lambda d, u: f"{u} continued task as: {d.get('new_title', '?')}",
    ActionType.SENSOR_SUBMITTED:        lambda d, u: f"{u} submitted {d.get('sensor_label', 'a form')}",
    ActionType.DOCUMENT_UPLOADED:       lambda d, u: f"{u} uploaded: {d.get('name', 'a document')}",
    ActionType.DOCUMENT_VERSIONED:      lambda d, u: f"{u} updated {d.get('name', '?')} (v{d.get('version', '?')})",
    ActionType.MEMBER_ADDED:            lambda d, u: f"{d.get('username', 'User')} added as {d.get('role', '?')}",
    ActionType.MEMBER_REMOVED:          lambda d, u: f"{d.get('username', 'User')} removed from room",
    ActionType.ROOM_CREATED:            lambda d, u: f"Room \"{d.get('name', '?')}\" created by {u}",
    ActionType.WORKFLOW_STARTED:        lambda d, u: f"{u} started workflow: {d.get('title', '?')}",
    ActionType.WORKFLOW_STEP_ADVANCED:  lambda d, u: f"{u} advanced workflow to {d.get('step_label', 'next step')}",
    ActionType.WORKFLOW_COMPLETED:      lambda d, u: f"Workflow \"{d.get('title', '?')}\" completed",
    ActionType.WORKFLOW_STALLED:        lambda d, u: f"Workflow \"{d.get('title', '?')}\" stalled — no action for {d.get('hours', '?')}h",
    ActionType.WORKFLOW_BYPASSED:       lambda d, u: f"{u} bypassed workflow: {d.get('reason', 'no reason given')}",
    ActionType.QA_SIGNED_OFF:           lambda d, u: f"{u} signed off QA",
    ActionType.PERMISSION_GRANTED:      lambda d, u: f"{u} granted permission: {d.get('action', '?')}",
    ActionType.PERMISSION_REVOKED:      lambda d, u: f"{u} revoked permission: {d.get('action', '?')}",
}


def format_event(action: str, detail: dict, actor_name: str) -> str:
    try:
        at = ActionType(action)
        fmt = _FMT.get(at)
        if fmt:
            return fmt(detail, actor_name)
    except ValueError:
        pass
    return f"{actor_name}: {action.replace('_', ' ').title()}"


# ---------------------------------------------------------------------------
# AuditService
# ---------------------------------------------------------------------------

class AuditService:

    def append(
        self,
        room_id:     RoomId,
        user_id:     UserId,
        username:    str,
        action_type: ActionType,
        detail:      dict,
        success:     bool = True,
    ) -> None:
        """The one and only write path into audit_log."""
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO audit_log
                   (log_id, timestamp, user_id, username, action, resource, details, success)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    datetime.utcnow().isoformat(),
                    user_id,
                    username,
                    action_type.value,
                    room_id,
                    json.dumps(detail),
                    1 if success else 0,
                ),
            )

    def query(
        self,
        room_id:      RoomId,
        actor:        User,
        since:        Optional[datetime] = None,
        action_types: Optional[List[ActionType]] = None,
        limit:        int = 100,
    ) -> List[dict]:
        """Query the audit log, role-filtered. Returns newest first."""
        from core.auth.rbac import get_room_role
        role = get_room_role(actor, room_id)

        clauses = ["resource = ?"]
        params: list = [room_id]

        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())

        if action_types:
            ph = ",".join("?" * len(action_types))
            clauses.append(f"action IN ({ph})")
            params.extend(at.value for at in action_types)

        # Viewers see only their own events
        if role == RoomRole.VIEWER:
            clauses.append("user_id = ?")
            params.append(actor.user_id)

        where = " AND ".join(clauses)
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM audit_log WHERE {where} ORDER BY seq DESC LIMIT ?",
                params,
            ).fetchall()

        return [
            {
                "seq":       row["seq"],
                "log_id":    row["log_id"],
                "timestamp": row["timestamp"],
                "username":  row["username"] or "System",
                "action":    row["action"],
                "detail":    json.loads(row["details"] or "{}"),
                "message":   format_event(
                    row["action"],
                    json.loads(row["details"] or "{}"),
                    row["username"] or "System",
                ),
                "success":   bool(row["success"]),
            }
            for row in rows
        ]

    def verify_integrity(self, room_id: Optional[RoomId] = None) -> dict:
        """
        Check for gaps in the sequential audit log.
        A missing seq value means a row was deleted — a protocol violation.
        """
        with get_connection() as conn:
            if room_id:
                rows = conn.execute(
                    "SELECT seq FROM audit_log WHERE resource = ? ORDER BY seq",
                    (room_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT seq FROM audit_log ORDER BY seq"
                ).fetchall()

        seqs = [r["seq"] for r in rows]
        if not seqs:
            return {"ok": True, "checked": 0}

        expected = set(range(seqs[0], seqs[-1] + 1))
        missing = sorted(expected - set(seqs))

        if missing:
            return {
                "ok":           False,
                "missing_seqs": missing,
                "gap_count":    len(missing),
                "first_seq":    seqs[0],
                "last_seq":     seqs[-1],
            }
        return {"ok": True, "checked": len(seqs)}


audit_service = AuditService()