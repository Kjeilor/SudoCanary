"""
core/workflows/workflow_impl.py

WorkflowService: manages workflow instances and step advancement.

advance_step():
  - Validates the instance is not terminal
  - Reads the next step from workflow_steps (by step_order)
  - Writes a workflow_step_history record
  - Updates the instance's current step and status
  - Writes WORKFLOW_STEP_ADVANCED to audit_log
  - All in one transaction

Role enforcement: any Officer in the room can advance any step on Day 6.
Fine-grained role matching (per required_role field) is added when the
full Role enum reconciliation happens.

SLA stalled detection: compare current step's sla_hours against
the most recent step_history entry's advanced_at timestamp.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from core.auth.rbac import require_officer, require_room_access
from core.db.connection import get_connection
from core.models.user import User
from core.sdk.types import ActionType, RoomId, UserId


class WorkflowService:

    # ── Advance ───────────────────────────────────────────────────────────────

    def advance_step(
        self,
        actor: User,
        instance_id: str,
        notes: str = "",
        payload: Optional[dict] = None,
    ) -> dict:
        """
        Advance a running workflow instance to its next step.
        Returns the updated instance dict.
        """
        with get_connection() as conn:
            inst = conn.execute(
                "SELECT * FROM workflow_instances WHERE instance_id=?",
                (instance_id,),
            ).fetchone()

        if not inst:
            raise ValueError(f"Instance '{instance_id}' not found")
        if inst["status"] in ("complete", "cancelled"):
            raise ValueError(
                f"Cannot advance a {inst['status']} workflow instance."
            )

        require_officer(actor, RoomId(inst["room_id"]))

        current_step = self._get_step(
            inst["current_step_id"], inst["workflow_id"], inst["room_id"]
        )
        if not current_step:
            raise ValueError(
                f"Step definition '{inst['current_step_id']}' not found. "
                "Ensure workflow_steps are seeded."
            )

        next_order = (current_step["step_order"] or 1) + 1
        next_step = self._get_step_by_order(
            inst["workflow_id"], inst["room_id"], next_order
        )

        now = datetime.utcnow().isoformat()
        record_id = str(uuid.uuid4())

        with get_connection() as conn:
            conn.execute(
                "INSERT INTO workflow_step_history "
                "(record_id, instance_id, step_id, advanced_by, advanced_at, notes, payload) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    record_id, instance_id,
                    inst["current_step_id"], str(actor.user_id),
                    now, notes,
                    json.dumps(payload) if payload else None,
                ),
            )

            if next_step:
                is_terminal = bool(next_step["is_terminal"])
                new_status = "complete" if is_terminal else "active"
                conn.execute(
                    "UPDATE workflow_instances "
                    "SET current_step_id=?, current_step_label=?, status=? "
                    "WHERE instance_id=?",
                    (next_step["step_id"], next_step["label"], new_status, instance_id),
                )
                next_step_id = next_step["step_id"]
            else:
                conn.execute(
                    "UPDATE workflow_instances SET status='complete' WHERE instance_id=?",
                    (instance_id,),
                )
                new_status = "complete"
                next_step_id = "complete"

            conn.execute(
                "INSERT INTO audit_log "
                "(log_id, timestamp, user_id, username, action, resource, details, success) "
                "VALUES (?,?,?,?,?,?,?,1)",
                (
                    str(uuid.uuid4()), now,
                    str(actor.user_id), actor.username,
                    ActionType.WORKFLOW_STEP_ADVANCED.value,
                    inst["room_id"],
                    json.dumps({
                        "instance_id":  instance_id,
                        "title":        inst["title"],
                        "from_step":    inst["current_step_id"],
                        "to_step":      next_step_id,
                        "new_status":   new_status,
                    }),
                ),
            )

        return self.get_instance(instance_id)

    def cancel_instance(
        self, actor: User, instance_id: str, reason: str
    ) -> None:
        from core.auth.rbac import require_admin
        with get_connection() as conn:
            inst = conn.execute(
                "SELECT * FROM workflow_instances WHERE instance_id=?",
                (instance_id,),
            ).fetchone()
        if not inst:
            raise ValueError(f"Instance '{instance_id}' not found")
        require_admin(actor)
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            conn.execute(
                "UPDATE workflow_instances SET status='cancelled' WHERE instance_id=?",
                (instance_id,),
            )
            conn.execute(
                "INSERT INTO audit_log "
                "(log_id, timestamp, user_id, username, action, resource, details, success) "
                "VALUES (?,?,?,?,?,?,?,1)",
                (
                    str(uuid.uuid4()), now,
                    str(actor.user_id), actor.username,
                    ActionType.WORKFLOW_CANCELLED.value,
                    inst["room_id"],
                    json.dumps({"instance_id": instance_id, "reason": reason}),
                ),
            )

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_instance(self, instance_id: str) -> dict:
        with get_connection() as conn:
            inst = conn.execute(
                "SELECT wi.*, u.display_name as initiator_name "
                "FROM workflow_instances wi "
                "LEFT JOIN users u ON wi.initiated_by = u.user_id "
                "WHERE wi.instance_id=?",
                (instance_id,),
            ).fetchone()
            if not inst:
                raise ValueError(f"Instance '{instance_id}' not found")

            history = conn.execute(
                "SELECT wsh.*, u.display_name as advancer_name "
                "FROM workflow_step_history wsh "
                "LEFT JOIN users u ON wsh.advanced_by = u.user_id "
                "WHERE wsh.instance_id=? "
                "ORDER BY wsh.advanced_at",
                (instance_id,),
            ).fetchall()

            steps = conn.execute(
                "SELECT * FROM workflow_steps "
                "WHERE workflow_id=? AND room_id=? ORDER BY step_order",
                (inst["workflow_id"], inst["room_id"]),
            ).fetchall()

        result = dict(inst)
        result["step_history"] = [dict(h) for h in history]
        result["all_steps"] = [dict(s) for s in steps]
        result["current_step_def"] = self._get_step(
            inst["current_step_id"], inst["workflow_id"], inst["room_id"]
        )
        return result

    def list_instances(
        self,
        actor: User,
        room_id: RoomId,
        status: Optional[str] = None,
    ) -> List[dict]:
        require_room_access(actor, room_id)
        clauses = ["wi.room_id = ?"]
        params: list = [str(room_id)]
        if status:
            clauses.append("wi.status = ?")
            params.append(status)

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT wi.*, u.display_name as initiator_name "
                "FROM workflow_instances wi "
                "LEFT JOIN users u ON wi.initiated_by = u.user_id "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY CASE wi.status WHEN 'stalled' THEN 0 ELSE 1 END, wi.started_at DESC",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_sla_remaining(self, instance: dict) -> Optional[str]:
        """Return human-readable SLA remaining for current step, or None."""
        step_def = instance.get("current_step_def")
        if not step_def or not step_def.get("sla_hours"):
            return None
        history = instance.get("step_history", [])
        if history:
            last_advance = datetime.fromisoformat(history[-1]["advanced_at"])
        else:
            last_advance = datetime.fromisoformat(instance["started_at"])

        deadline = last_advance + timedelta(hours=step_def["sla_hours"])
        remaining = deadline - datetime.utcnow()

        if remaining.total_seconds() < 0:
            hours_over = abs(int(remaining.total_seconds() / 3600))
            return f"Overdue by {hours_over}h"
        hours_left = int(remaining.total_seconds() / 3600)
        return f"{hours_left}h remaining"

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_step(
        self, step_id: str, workflow_id: str, room_id: str
    ) -> Optional[dict]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_steps "
                "WHERE step_id=? AND workflow_id=? AND room_id=?",
                (step_id, workflow_id, room_id),
            ).fetchone()
        return dict(row) if row else None

    def _get_step_by_order(
        self, workflow_id: str, room_id: str, order: int
    ) -> Optional[dict]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_steps "
                "WHERE workflow_id=? AND room_id=? AND step_order=?",
                (workflow_id, room_id, order),
            ).fetchone()
        return dict(row) if row else None


workflow_service = WorkflowService()