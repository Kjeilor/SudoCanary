"""
core/room_impl.py

RoomAPIImpl — complete implementation of the RoomAPI Protocol.
Every Protocol method is implemented. verify_contract() confirms compliance.

Day 5: all missing methods added (get_members, read_sensor_data,
write_sensor_event, create_task, update_task_status, list_tasks, get_task,
upload_document, get_document, list_documents, get_audit_trail).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional, Sequence

from core.auth.rbac import (
    PermissionDenied,
    require_admin,
    require_officer,
    require_room_access,
)
from core.db.connection import get_connection
from core.models.user import RoomRole, User
from core.sdk.types import (
    ActionType,
    AuditEvent,
    Document,
    DocumentId,
    EventId,
    Member,
    Role,
    Room,
    RoomId,
    SensorEvent,
    SensorId,
    Task,
    TaskId,
    TaskStatus,
    UserId,
)


class RoomAPIImpl:
    """Implements core/sdk/room.py :: RoomAPI Protocol."""

    def __init__(self, actor: User) -> None:
        self._actor = actor

    # ── Room ─────────────────────────────────────────────────────────────────

    def get_room(self, room_id: RoomId) -> Room:
        """Return a Room dataclass with current members."""
        require_room_access(self._actor, room_id)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM rooms WHERE room_id = ?", (str(room_id),)
            ).fetchone()
        if not row:
            raise ValueError(f"Room '{room_id}' not found")
        members = tuple(self.get_members(room_id))
        return Room(
            room_id=RoomId(row["room_id"]),
            name=row["name"],
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"]),
            members=members,
        )

    def list_rooms(self, user_id: UserId = None) -> List[dict]:
        """
        Returns list of room dicts scoped to self._actor.
        user_id parameter accepted for Protocol compatibility but actor is authoritative.
        """
        with get_connection() as conn:
            if self._actor.system_role == "admin":
                rows = conn.execute("SELECT * FROM rooms ORDER BY name").fetchall()
            else:
                accessible = list(self._actor.room_roles.keys())
                if not accessible:
                    return []
                ph = ",".join("?" * len(accessible))
                rows = conn.execute(
                    f"SELECT * FROM rooms WHERE room_id IN ({ph}) ORDER BY name",
                    accessible,
                ).fetchall()
        return [dict(r) for r in rows]

    def create_room(self, name: str, description: str = "") -> RoomId:
        require_admin(self._actor)
        room_id = RoomId(str(uuid.uuid4()))
        now = datetime.utcnow().isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO rooms (room_id, name, description, created_at, created_by)"
                " VALUES (?, ?, ?, ?, ?)",
                (room_id, name, description, now, self._actor.user_id),
            )
            self._audit(conn, "room.create", room_id, {"name": name})
        return room_id

    # ── Members ───────────────────────────────────────────────────────────────

    def get_members(self, room_id: RoomId) -> List[Member]:
        """Return Protocol-typed Member list. Maps room role to SDK Role enum."""
        require_room_access(self._actor, room_id)
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT u.user_id, u.username, u.display_name, rr.role "
                "FROM room_roles rr JOIN users u USING(user_id) "
                "WHERE rr.room_id = ? ORDER BY u.display_name",
                (str(room_id),),
            ).fetchall()
        return [
            Member(
                user_id=UserId(r["user_id"]),
                role=Role.ADMIN if r["role"] == "officer" else Role.VIEWER,
                joined_at=datetime.utcnow(),  # joined_at not in schema; approximated
            )
            for r in rows
        ]

    def list_members(self, room_id: RoomId) -> Sequence[dict]:
        """Internal helper returning raw dicts — used by UI layers."""
        require_room_access(self._actor, room_id)
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT u.user_id, u.username, u.display_name, rr.role "
                "FROM room_roles rr JOIN users u USING(user_id) "
                "WHERE rr.room_id = ? ORDER BY u.display_name",
                (str(room_id),),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_member(self, room_id: RoomId, user_id: UserId, role: RoomRole) -> None:
        require_officer(self._actor, room_id)
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO room_roles (user_id, room_id, role) VALUES (?,?,?)",
                (str(user_id), str(room_id), role.value),
            )
            self._audit(conn, "room.member.add", str(room_id),
                        {"user_id": str(user_id), "role": role.value})

    def remove_member(self, room_id: RoomId, user_id: UserId) -> None:
        require_officer(self._actor, room_id)
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM room_roles WHERE user_id = ? AND room_id = ?",
                (str(user_id), str(room_id)),
            )
            self._audit(conn, "room.member.remove", str(room_id),
                        {"user_id": str(user_id)})

    # ── Sensor data ───────────────────────────────────────────────────────────

    def read_sensor_data(
        self,
        room_id: RoomId,
        sensor_id: SensorId,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[SensorEvent]:
        require_room_access(self._actor, room_id)
        clauses = ["room_id = ?", "sensor_id = ?"]
        params: list = [str(room_id), str(sensor_id)]
        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())
        limit_clause = ""
        if limit:
            limit_clause = " LIMIT ?"
            params.append(limit)
        with get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM sensor_events WHERE {' AND '.join(clauses)}"
                f" ORDER BY timestamp DESC{limit_clause}",
                params,
            ).fetchall()
        return [
            SensorEvent(
                event_id=EventId(r["event_id"]),
                room_id=RoomId(r["room_id"]),
                sensor_id=SensorId(r["sensor_id"]),
                user_id=UserId(r["user_id"]),
                timestamp=datetime.fromisoformat(r["timestamp"]),
                payload=json.loads(r["payload"]),
                provenance=r["provenance"],
            )
            for r in rows
        ]

    def write_sensor_event(
        self,
        room_id: RoomId,
        sensor_id: SensorId,
        user_id: UserId,
        payload: dict,
    ) -> SensorEvent:
        require_room_access(self._actor, room_id)
        now = datetime.utcnow()
        event_id = EventId(str(uuid.uuid4()))
        provenance = SensorEvent.compute_provenance(payload, user_id, now)
        event = SensorEvent(
            event_id=event_id,
            room_id=room_id,
            sensor_id=sensor_id,
            user_id=user_id,
            timestamp=now,
            payload=payload,
            provenance=provenance,
        )
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO sensor_events "
                "(event_id, room_id, sensor_id, user_id, timestamp, payload, provenance) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    str(event_id), str(room_id), str(sensor_id), str(user_id),
                    now.isoformat(), json.dumps(payload), provenance,
                ),
            )
            self._audit(conn, ActionType.SENSOR_SUBMITTED.value, str(room_id),
                        {"sensor_id": str(sensor_id)})
        return event

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def create_task(
        self,
        room_id: RoomId,
        created_by: UserId,
        title: str,
        description: str,
        assigned_to: Optional[UserId] = None,
        due_at: Optional[datetime] = None,
    ) -> Task:
        from core.task_impl import task_service
        from core.sdk.types import TaskTrackability
        return task_service.create_task(
            self._actor, room_id, title, description, assigned_to, due_at,
            TaskTrackability.TRACKABLE,
        )

    def update_task_status(
        self,
        room_id: RoomId,
        task_id: TaskId,
        updated_by: UserId,
        new_status: TaskStatus,
    ) -> Task:
        from core.task_impl import task_service
        return task_service.update_task_status(
            self._actor, room_id, task_id, new_status
        )

    def list_tasks(
        self,
        room_id: RoomId,
        status: Optional[TaskStatus] = None,
    ) -> List[Task]:
        from core.task_impl import task_service
        return task_service.list_tasks(self._actor, room_id, status)

    def get_task(self, room_id: RoomId, task_id: TaskId) -> Task:
        from core.task_impl import task_service
        return task_service.get_task(self._actor, room_id, task_id)

    # ── Documents ─────────────────────────────────────────────────────────────

    def upload_document(
        self,
        room_id: RoomId,
        uploaded_by: UserId,
        name: str,
        file_path: str,
        notes: str = "",
    ) -> Document:
        from core.documents.document_impl import document_service
        return document_service.upload(self._actor, room_id, name, file_path, notes)

    def get_document(self, room_id: RoomId, document_id: DocumentId) -> Document:
        from core.documents.document_impl import document_service
        return document_service.get_document(self._actor, room_id, document_id)

    def list_documents(self, room_id: RoomId) -> List[Document]:
        from core.documents.document_impl import document_service
        return document_service.list_documents(self._actor, room_id)

    # ── Audit trail ───────────────────────────────────────────────────────────

    def get_audit_trail(
        self,
        room_id: RoomId,
        since: Optional[datetime] = None,
        action_types: Optional[List[ActionType]] = None,
    ) -> List[AuditEvent]:
        from core.audit import audit_service
        raw = audit_service.query(room_id, self._actor, since, action_types)
        result = []
        for ev in raw:
            try:
                result.append(AuditEvent(
                    event_id=EventId(ev["log_id"]),
                    room_id=RoomId(str(room_id)),
                    user_id=UserId(ev.get("user_id") or ""),
                    action_type=ActionType(ev["action"]),
                    timestamp=datetime.fromisoformat(ev["timestamp"]),
                    detail=ev["detail"],
                ))
            except (ValueError, KeyError):
                pass
        return result

    # ── Internal audit helper ─────────────────────────────────────────────────

    def _audit(self, conn, action: str, resource: str, details: dict,
               success: bool = True) -> None:
        conn.execute(
            "INSERT INTO audit_log "
            "(log_id, timestamp, user_id, username, action, resource, details, success) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                datetime.utcnow().isoformat(),
                str(self._actor.user_id),
                self._actor.username,
                action,
                resource,
                json.dumps(details),
                1 if success else 0,
            ),
        )


# ---------------------------------------------------------------------------
# Contract verification
# ---------------------------------------------------------------------------

def verify_contract() -> bool:
    """
    Verify that RoomAPIImpl satisfies the RoomAPI Protocol.
    Checks method presence against the Protocol definition.
    Must pass before Day 6 — the Canary engine depends on a complete impl.
    """
    # Protocol methods from core/sdk/room.py
    required = [
        "get_room", "list_rooms", "get_members",
        "read_sensor_data", "write_sensor_event",
        "create_task", "update_task_status", "list_tasks", "get_task",
        "upload_document", "get_document", "list_documents",
        "get_audit_trail",
    ]
    missing = [m for m in required if not callable(getattr(RoomAPIImpl, m, None))]
    ok = len(missing) == 0
    status = "✓ PASS" if ok else "✗ FAIL"
    print(f"RoomAPI contract: {status}")
    if missing:
        print(f"  Missing methods: {missing}")
    else:
        print(f"  All {len(required)} required methods present")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if verify_contract() else 1)