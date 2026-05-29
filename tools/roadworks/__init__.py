"""
tools/roadworks/__init__.py

RoadWorksTool — implements ToolInterface Protocol.

install() registers four sensors, three Canary producers, and one
visualisation panel per room. Writes to installed_tools table.
uninstall() removes sensors and producers. Never deletes event history.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, List

from core.sdk.permissions import Action, PermissionsDeclaration
from core.sdk.types import ToolId, RoomId

from tools.roadworks.sensors import (
    KM_PROGRESS_SCHEMA, MATERIALS_SCHEMA,
    QA_SIGNOFF_SCHEMA, PHOTO_CHECKIN_SCHEMA,
    km_progress_callback, materials_callback,
    qa_signoff_callback,
)
from tools.roadworks.producers import (
    progress_producer, materials_producer, rw_activity_producer,
)


_DEFAULT_CONFIG = {
    "divergence_amber": 15,
    "divergence_red":   30,
    "stale_hours":      48,
}

_SENSORS = [
    ("roadworks.km_progress",  "Daily KM Progress",    KM_PROGRESS_SCHEMA, km_progress_callback),
    ("roadworks.materials_log","Materials Log",         MATERIALS_SCHEMA,   materials_callback),
    ("roadworks.qa_signoff",   "QA Section Sign-off",  QA_SIGNOFF_SCHEMA,  qa_signoff_callback),
    ("roadworks.photo_checkin","Site Photo Check-in",   PHOTO_CHECKIN_SCHEMA, None),
]


class RoadWorksTool:
    tool_id      = ToolId("roadworks")
    tool_name    = "RoadWorks"
    tool_version = "1.0.0"
    description  = "Infrastructure project management for road reconstruction."

    # ── Protocol methods ──────────────────────────────────────────────────────

    def get_permissions(self) -> PermissionsDeclaration:
        return PermissionsDeclaration(
            tool_id=self.tool_id,
            required_rooms=[],
            required_actions=[
                Action.READ_SENSOR_DATA,
                Action.WRITE_SENSOR_EVENT,
                Action.WRITE_CANARY_OUTPUTS,
                Action.REGISTER_PANEL,
            ],
            optional_actions=[Action.READ_AUDIT_TRAIL],
            justification=(
                "RoadWorks reads and writes sensor data for KM progress, "
                "materials tracking, QA sign-off, and photo check-ins. "
                "It registers a section status map panel and writes Canary "
                "outputs to drive the room's health indicators."
            ),
        )

    def get_sensors(self) -> list:
        from core.sensors.form_sensor import FormSensorImpl
        from core.sensors.qr_checkin import QRCheckInSensorImpl
        from core.sdk.types import SensorId
        result = []
        for sid, label, schema, cb in _SENSORS:
            if schema.get("x-sensor-type") == "qr_checkin":
                result.append(QRCheckInSensorImpl(
                    SensorId(sid), RoomId("__template__"), label, schema, 48,
                ))
            else:
                result.append(FormSensorImpl(
                    SensorId(sid), RoomId("__template__"), label, schema, cb,
                    "roadworks",
                ))
        return result

    def install(
        self,
        room_ids: List[RoomId],
        room_api: Any,
        canary: Any,
        viz_registry: Any,
        permissions: Any,
    ) -> None:
        from core.db.connection import get_connection
        from core.sensors.form_sensor import sensor_service
        from core.sensors.qr_checkin import QRCheckInSensorImpl
        from core.canary_engine import canary_engine
        from core.sdk.types import SensorId
        from tools.roadworks.map_panel import RoadWorksMapPanel

        actor_id = str(room_api._actor.user_id) if hasattr(room_api, "_actor") else ""
        now = datetime.utcnow().isoformat()
        config_json = json.dumps(_DEFAULT_CONFIG)

        for room_id in room_ids:
            rid = str(room_id)

            # Register sensors
            for sid, label, schema, cb in _SENSORS:
                sensor_service.register(
                    sensor_id=sid,
                    room_id=rid,
                    label=label,
                    schema=schema,
                    tool_id="roadworks",
                    on_submit_callback=cb,
                )

            # Register Canary producers
            canary_engine.register_producer(room_id, "roadworks.progress",  progress_producer)
            canary_engine.register_producer(room_id, "roadworks.materials", materials_producer)
            canary_engine.register_producer(room_id, "roadworks.activity",  rw_activity_producer)

            # Register map panel (scaffold — renders Day 9)
            panel = RoadWorksMapPanel(rid)
            try:
                viz_registry.register_panel(panel)
            except Exception:
                pass

            # Write installed_tools row
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO installed_tools "
                    "(room_id, tool_id, installed_by, installed_at, config) "
                    "VALUES (?,?,?,?,?)",
                    (rid, "roadworks", actor_id, now, config_json),
                )
                conn.execute(
                    "INSERT INTO audit_log "
                    "(log_id, timestamp, user_id, username, action, resource, details, success) "
                    "VALUES (?,?,?,?,?,?,?,1)",
                    (
                        str(uuid.uuid4()), now, actor_id, "",
                        "tool.installed", rid,
                        json.dumps({"tool_id": "roadworks", "version": self.tool_version}),
                    ),
                )

    def uninstall(self, room_ids: List[RoomId]) -> None:
        from core.db.connection import get_connection
        from core.sensors.form_sensor import sensor_service
        from core.canary_engine import canary_engine

        for room_id in room_ids:
            rid = str(room_id)

            # Remove sensors
            for sid, _, _, _ in _SENSORS:
                sensor_service.delete(sid, rid)

            # Remove producers
            if rid in canary_engine._room_producers:
                for key in ["roadworks.progress", "roadworks.materials", "roadworks.activity"]:
                    canary_engine._room_producers[rid].pop(key, None)

            with get_connection() as conn:
                conn.execute(
                    "DELETE FROM installed_tools WHERE room_id=? AND tool_id='roadworks'",
                    (rid,),
                )
                conn.execute(
                    "INSERT INTO audit_log "
                    "(log_id, timestamp, user_id, username, action, resource, details, success) "
                    "VALUES (?,?,?,?,?,?,?,1)",
                    (
                        str(uuid.uuid4()), datetime.utcnow().isoformat(), "", "",
                        "tool.uninstalled", rid,
                        json.dumps({"tool_id": "roadworks"}),
                    ),
                )