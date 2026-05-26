"""
core/canary_engine.py

Domain-agnostic Canary engine.

compute(room_id) → CanaryState
    Runs all registered producers (global built-ins + room-specific Tool
    producers), writes state to canary_states + canary_outputs, notifies
    subscribers, returns CanaryState.

subscribe(room_id, callback) → subscription_id
    Callback is called on the main thread — no QMetaObject needed on Day 6.
    Thread safety added on Day 9 when Leaflet tile loading introduces threads.

Global built-in producers (always run for any room):
    builtin.tasks      — open, overdue, completion rate
    builtin.workflows  — active, stalled, completion rate
    builtin.activity   — last event, events today, stale check-ins

Tools register room-specific producers via register_producer() on Day 10.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from core.db.connection import get_connection
from core.sdk.types import CanaryOutput, CanaryState, RoomId


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def _overall_status(outputs: List[CanaryOutput]) -> str:
    if not outputs:
        return "grey"
    statuses = {o.status for o in outputs}
    if "red" in statuses:
        return "red"
    if "amber" in statuses:
        return "amber"
    if all(o.status == "green" for o in outputs):
        return "green"
    return "grey"


def _get_stale_threshold(room_id: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT stale_threshold FROM room_settings WHERE room_id=?",
            (room_id,),
        ).fetchone()
    return row["stale_threshold"] if row else 3


# ---------------------------------------------------------------------------
# Built-in producers
# ---------------------------------------------------------------------------

def _task_producer(room_id: str, events: list) -> List[CanaryOutput]:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        open_c = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE room_id=? AND status='open'", (room_id,)
        ).fetchone()[0]
        in_prog = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE room_id=? AND status='in_progress'", (room_id,)
        ).fetchone()[0]
        overdue = conn.execute(
            "SELECT COUNT(*) FROM tasks "
            "WHERE room_id=? AND status IN ('open','in_progress') AND due_at < ?",
            (room_id, now),
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE room_id=?", (room_id,)
        ).fetchone()[0]
        complete = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE room_id=? AND status='complete'", (room_id,)
        ).fetchone()[0]

    active = open_c + in_prog
    now_dt = datetime.utcnow()

    if active == 0:
        task_status = "green"
    elif active <= 5:
        task_status = "amber"
    else:
        task_status = "red"

    overdue_status = "red" if overdue > 0 else "green"

    rate = (complete / total * 100) if total > 0 else 0
    rate_status = "green" if rate >= 50 else "amber"

    return [
        CanaryOutput(
            key="tasks.open",
            label="Open Tasks",
            value=str(active),
            status=task_status,
            updated_at=now_dt,
            detail=f"{open_c} open  ·  {in_prog} in progress",
        ),
        CanaryOutput(
            key="tasks.overdue",
            label="Overdue Tasks",
            value=str(overdue),
            status=overdue_status,
            updated_at=now_dt,
            detail="Tasks past their due date",
        ),
        CanaryOutput(
            key="tasks.completion_rate",
            label="Task Completion",
            value=f"{rate:.0f}%",
            status=rate_status,
            updated_at=now_dt,
            detail=f"{complete} of {total} tasks completed",
        ),
    ]


def _workflow_producer(room_id: str, events: list) -> List[CanaryOutput]:
    now_dt = datetime.utcnow()
    with get_connection() as conn:
        active = conn.execute(
            "SELECT COUNT(*) FROM workflow_instances WHERE room_id=? AND status='active'",
            (room_id,),
        ).fetchone()[0]
        stalled = conn.execute(
            "SELECT COUNT(*) FROM workflow_instances WHERE room_id=? AND status='stalled'",
            (room_id,),
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM workflow_instances WHERE room_id=?", (room_id,)
        ).fetchone()[0]
        complete = conn.execute(
            "SELECT COUNT(*) FROM workflow_instances WHERE room_id=? AND status='complete'",
            (room_id,),
        ).fetchone()[0]

    stalled_status = "red" if stalled > 0 else "green"
    rate = (complete / total * 100) if total > 0 else 0
    rate_status = "green" if rate >= 50 else "amber"

    return [
        CanaryOutput(
            key="workflows.active",
            label="Active Workflows",
            value=str(active),
            status="green" if active >= 0 else "grey",
            updated_at=now_dt,
            detail=f"{active} instance(s) in progress",
        ),
        CanaryOutput(
            key="workflows.stalled",
            label="Stalled Workflows",
            value=str(stalled),
            status=stalled_status,
            updated_at=now_dt,
            detail="Instances where SLA has been exceeded",
        ),
        CanaryOutput(
            key="workflows.completion_rate",
            label="Workflow Completion",
            value=f"{rate:.0f}%",
            status=rate_status,
            updated_at=now_dt,
            detail=f"{complete} of {total} instances completed",
        ),
    ]


def _activity_producer(room_id: str, events: list) -> List[CanaryOutput]:
    now_dt = datetime.utcnow()
    today_start = (now_dt - timedelta(hours=24)).isoformat()
    threshold = _get_stale_threshold(room_id)
    stale_cutoff = (now_dt - timedelta(hours=48)).isoformat()

    with get_connection() as conn:
        last_row = conn.execute(
            "SELECT timestamp FROM audit_log WHERE resource=? ORDER BY seq DESC LIMIT 1",
            (room_id,),
        ).fetchone()
        events_today = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE resource=? AND timestamp >= ?",
            (room_id, today_start),
        ).fetchone()[0]

        # Stale check-ins: entities with last check-in > 48h ago
        entity_rows = conn.execute(
            "SELECT pc.entity_id, MAX(se.timestamp) as last_ts "
            "FROM photo_checkins pc "
            "JOIN sensor_events se ON pc.event_id = se.event_id "
            "WHERE se.room_id=? "
            "GROUP BY pc.entity_id",
            (room_id,),
        ).fetchall()

    stale_count = sum(1 for r in entity_rows if r["last_ts"] < stale_cutoff)

    last_event_str = last_row["timestamp"][:16].replace("T", " ") if last_row else "Never"
    activity_status = "green" if events_today > 0 else "amber"

    if stale_count == 0:
        stale_status = "green"
    elif stale_count <= threshold:
        stale_status = "amber"
    else:
        stale_status = "red"

    return [
        CanaryOutput(
            key="activity.last_event",
            label="Last Activity",
            value=last_event_str,
            status=activity_status,
            updated_at=now_dt,
            detail=f"{events_today} event(s) in the last 24h",
        ),
        CanaryOutput(
            key="activity.stale_checkins",
            label="Stale Check-ins",
            value=str(stale_count),
            status=stale_status,
            updated_at=now_dt,
            detail=f"Entities with no check-in in 48h (threshold: {threshold})",
        ),
    ]


# ---------------------------------------------------------------------------
# Canary Engine
# ---------------------------------------------------------------------------

_GLOBAL_PRODUCERS = {
    "builtin.tasks":     _task_producer,
    "builtin.workflows": _workflow_producer,
    "builtin.activity":  _activity_producer,
}


class CanaryEngine:
    """
    Domain-agnostic Canary engine. Module-level singleton: canary_engine.
    """

    def __init__(self) -> None:
        self._room_producers: Dict[str, Dict[str, Callable]] = {}
        self._subscriptions: Dict[str, Tuple[str, Callable]] = {}

    def register_producer(
        self,
        room_id: RoomId,
        producer_id: str,
        producer: Callable,
    ) -> None:
        """Register a room-specific producer (called by Tools on Day 10)."""
        key = str(room_id)
        if key not in self._room_producers:
            self._room_producers[key] = {}
        self._room_producers[key][producer_id] = producer

    def compute(self, room_id: RoomId) -> CanaryState:
        """
        Run all producers for the room, persist state, notify subscribers.
        Always computes fresh — no caching.
        """
        rid = str(room_id)
        now = datetime.utcnow()

        # Load sensor events for context (producers may use them)
        with get_connection() as conn:
            event_rows = conn.execute(
                "SELECT * FROM sensor_events WHERE room_id=? ORDER BY timestamp DESC LIMIT 500",
                (rid,),
            ).fetchall()
        events = [dict(r) for r in event_rows]

        # Run all producers
        all_outputs: List[CanaryOutput] = []

        for pid, producer in _GLOBAL_PRODUCERS.items():
            try:
                all_outputs.extend(producer(rid, events))
            except Exception as exc:
                all_outputs.append(CanaryOutput(
                    key=f"{pid}.error",
                    label=pid,
                    value="Error",
                    status="grey",
                    updated_at=now,
                    detail=str(exc),
                ))

        for pid, producer in self._room_producers.get(rid, {}).items():
            try:
                all_outputs.extend(producer(rid, events))
            except Exception:
                pass

        state = CanaryState(
            room_id=RoomId(rid),
            generated_at=now,
            outputs=tuple(all_outputs),
        )

        self._persist(state)
        self._notify(rid, state)
        return state

    def subscribe(
        self, room_id: RoomId, callback: Callable[[CanaryState], None]
    ) -> str:
        sub_id = str(uuid.uuid4())
        self._subscriptions[sub_id] = (str(room_id), callback)
        return sub_id

    def unsubscribe(self, sub_id: str) -> None:
        self._subscriptions.pop(sub_id, None)

    def get_latest_state(self, room_id: RoomId) -> Optional[CanaryState]:
        """Return the most recent persisted CanaryState without recomputing."""
        rid = str(room_id)
        with get_connection() as conn:
            state_row = conn.execute(
                "SELECT * FROM canary_states WHERE room_id=? "
                "ORDER BY generated_at DESC LIMIT 1",
                (rid,),
            ).fetchone()
            if not state_row:
                return None
            output_rows = conn.execute(
                "SELECT * FROM canary_outputs WHERE state_id=?",
                (state_row["state_id"],),
            ).fetchall()

        outputs = tuple(
            CanaryOutput(
                key=r["key"],
                label=r["label"],
                value=r["value"],
                status=r["status"],
                updated_at=datetime.fromisoformat(r["updated_at"]),
                detail=r["detail"],
            )
            for r in output_rows
        )
        return CanaryState(
            room_id=RoomId(rid),
            generated_at=datetime.fromisoformat(state_row["generated_at"]),
            outputs=outputs,
        )

    def get_overall_status(self, room_id: RoomId) -> str:
        """Quick status read for room card colouring. Reads latest persisted state."""
        state = self.get_latest_state(room_id)
        if state is None:
            return "grey"
        return _overall_status(list(state.outputs))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _persist(self, state: CanaryState) -> None:
        state_id = str(uuid.uuid4())
        now = state.generated_at.isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO canary_states (state_id, room_id, generated_at) VALUES (?,?,?)",
                (state_id, str(state.room_id), now),
            )
            for o in state.outputs:
                conn.execute(
                    "INSERT INTO canary_outputs "
                    "(output_id, state_id, key, label, value, status, detail, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        str(uuid.uuid4()), state_id,
                        o.key, o.label, str(o.value),
                        o.status, o.detail, o.updated_at.isoformat(),
                    ),
                )

    def _notify(self, room_id: str, state: CanaryState) -> None:
        for sub_id, (rid, callback) in list(self._subscriptions.items()):
            if rid == room_id:
                try:
                    callback(state)
                except Exception:
                    pass


# Module-level singleton
canary_engine = CanaryEngine()