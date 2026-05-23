"""
Task system implementation.

State machine — forward only:
  OPEN → IN_PROGRESS → COMPLETE
  OPEN → COMPLETE  (direct)
  OPEN / IN_PROGRESS → CANCELLED
  COMPLETE and CANCELLED are terminal.

OVERDUE is derived at read time. The DB stores OPEN or IN_PROGRESS.
When due_at < now and status IN (open, in_progress), effective status = OVERDUE.

continue_task() creates a follow-on task linked by parent_task_id.
The original COMPLETE task is immutable.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from core.audit import audit_service
from core.auth.rbac import get_room_role, require_officer, require_room_access
from core.db.connection import get_connection
from core.models.user import RoomRole, User
from core.sdk.types import (
    ActionType, RoomId, Task, TaskId, TaskStatus, TaskTrackability, UserId,
)

_TRANSITIONS = {
    TaskStatus.OPEN:        {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETE, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {TaskStatus.COMPLETE, TaskStatus.CANCELLED},
    TaskStatus.COMPLETE:    set(),
    TaskStatus.CANCELLED:   set(),
}


def _row_to_task(row) -> Task:
    due_at = datetime.fromisoformat(row["due_at"]) if row["due_at"] else None
    stored = TaskStatus(row["status"])
    if (
        stored in (TaskStatus.OPEN, TaskStatus.IN_PROGRESS)
        and due_at is not None
        and due_at < datetime.utcnow()
    ):
        effective = TaskStatus.OVERDUE
    else:
        effective = stored

    return Task(
        task_id=TaskId(row["task_id"]),
        room_id=RoomId(row["room_id"]),
        title=row["title"],
        description=row["description"] or "",
        created_by=UserId(row["created_by"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        trackability=TaskTrackability(row["trackability"]),
        assigned_to=UserId(row["assigned_to"]) if row["assigned_to"] else None,
        due_at=due_at,
        status=effective,
        parent_task_id=TaskId(row["parent_task_id"]) if row["parent_task_id"] else None,
    )


def _stored_status(task_id: TaskId) -> TaskStatus:
    """Read the actual stored status (not the derived OVERDUE)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
    return TaskStatus(row["status"]) if row else TaskStatus.CANCELLED


class TaskService:

    # ── Create ────────────────────────────────────────────────────────────────

    def create_task(
        self,
        actor:        User,
        room_id:      RoomId,
        title:        str,
        description:  str = "",
        assigned_to:  Optional[UserId] = None,
        due_at:       Optional[datetime] = None,
        trackability: TaskTrackability = TaskTrackability.TRACKABLE,
    ) -> Task:
        require_room_access(actor, room_id)
        task_id = TaskId(str(uuid.uuid4()))
        now = datetime.utcnow().isoformat()

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO tasks
                   (task_id, room_id, title, description, created_by, created_at,
                    trackability, assigned_to, due_at, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
                (
                    task_id, room_id, title, description,
                    actor.user_id, now, trackability.value,
                    assigned_to,
                    due_at.isoformat() if due_at else None,
                ),
            )

        audit_service.append(
            room_id, actor.user_id, actor.username,
            ActionType.TASK_CREATED,
            {"title": title, "assigned_to": assigned_to, "trackability": trackability.value},
        )
        return self.get_task(actor, room_id, task_id)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_task(self, actor: User, room_id: RoomId, task_id: TaskId) -> Task:
        require_room_access(actor, room_id)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ? AND room_id = ?",
                (task_id, room_id),
            ).fetchone()
        if not row:
            raise ValueError(f"Task {task_id!r} not found")
        return _row_to_task(row)

    def list_tasks(
        self,
        actor:       User,
        room_id:     RoomId,
        status:      Optional[TaskStatus] = None,
        assigned_to: Optional[UserId] = None,
    ) -> List[Task]:
        require_room_access(actor, room_id)
        clauses = ["room_id = ?"]
        params: list = [room_id]

        role = get_room_role(actor, room_id)
        if role == RoomRole.VIEWER:
            clauses.append("assigned_to = ?")
            params.append(actor.user_id)
        elif assigned_to:
            clauses.append("assigned_to = ?")
            params.append(assigned_to)

        if status and status != TaskStatus.OVERDUE:
            clauses.append("status = ?")
            params.append(status.value)

        where = " AND ".join(clauses)
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE {where} ORDER BY created_at DESC",
                params,
            ).fetchall()

        tasks = [_row_to_task(r) for r in rows]
        if status == TaskStatus.OVERDUE:
            tasks = [t for t in tasks if t.status == TaskStatus.OVERDUE]
        return tasks

    def count_by_status(self, actor: User, room_id: RoomId) -> dict:
        """Returns active, overdue, complete, cancelled counts for a room."""
        require_room_access(actor, room_id)
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            active = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE room_id=? AND status NOT IN ('complete','cancelled')",
                (room_id,),
            ).fetchone()[0]
            overdue = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE room_id=? AND status IN ('open','in_progress') AND due_at < ?",
                (room_id, now),
            ).fetchone()[0]
            complete = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE room_id=? AND status='complete'",
                (room_id,),
            ).fetchone()[0]
        return {"active": active, "overdue": overdue, "complete": complete}

    # ── Update ────────────────────────────────────────────────────────────────

    def update_task_status(
        self,
        actor:      User,
        room_id:    RoomId,
        task_id:    TaskId,
        new_status: TaskStatus,
        notes:      str = "",
    ) -> Task:
        task = self.get_task(actor, room_id, task_id)
        # OVERDUE is derived — get the actual stored status for transition check
        current = (
            _stored_status(task_id)
            if task.status == TaskStatus.OVERDUE
            else task.status
        )

        if new_status not in _TRANSITIONS.get(current, set()):
            raise ValueError(
                f"Transition {current.value!r} → {new_status.value!r} is not permitted."
            )

        with get_connection() as conn:
            conn.execute(
                "UPDATE tasks SET status = ? WHERE task_id = ?",
                (new_status.value, task_id),
            )

        action = (
            ActionType.TASK_COMPLETED
            if new_status == TaskStatus.COMPLETE
            else ActionType.TASK_PROGRESSED
        )
        audit_service.append(
            room_id, actor.user_id, actor.username, action,
            {"task_id": task_id, "title": task.title,
             "old_status": current.value, "new_status": new_status.value, "notes": notes},
        )
        return self.get_task(actor, room_id, task_id)

    def assign_task(
        self,
        actor:         User,
        room_id:       RoomId,
        task_id:       TaskId,
        assigned_to:   UserId,
        assignee_name: str = "",
    ) -> Task:
        require_officer(actor, room_id)
        with get_connection() as conn:
            conn.execute(
                "UPDATE tasks SET assigned_to = ? WHERE task_id = ?",
                (assigned_to, task_id),
            )
        audit_service.append(
            room_id, actor.user_id, actor.username,
            ActionType.TASK_ASSIGNED,
            {"task_id": task_id, "assigned_to": assigned_to, "assignee_name": assignee_name},
        )
        return self.get_task(actor, room_id, task_id)

    # ── Continue (terminal task follow-on) ────────────────────────────────────

    def continue_task(
        self,
        actor:             User,
        room_id:           RoomId,
        parent_task_id:    TaskId,
        title:             str,
        continuation_note: str,
        description:       str = "",
        assigned_to:       Optional[UserId] = None,
        due_at:            Optional[datetime] = None,
    ) -> Task:
        parent = self.get_task(actor, room_id, parent_task_id)
        if parent.status != TaskStatus.COMPLETE:
            raise ValueError("continue_task() can only be called on a COMPLETE task.")

        new_id = TaskId(str(uuid.uuid4()))
        now = datetime.utcnow().isoformat()

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO tasks
                   (task_id, room_id, title, description, created_by, created_at,
                    trackability, assigned_to, due_at, status, parent_task_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
                (
                    new_id, room_id, title, description,
                    actor.user_id, now, parent.trackability.value,
                    assigned_to,
                    due_at.isoformat() if due_at else None,
                    parent_task_id,
                ),
            )

        audit_service.append(
            room_id, actor.user_id, actor.username,
            ActionType.TASK_CONTINUED,
            {"parent_task_id": parent_task_id, "new_task_id": new_id,
             "new_title": title, "note": continuation_note},
        )
        return self.get_task(actor, room_id, new_id)


task_service = TaskService()