"""
core/sdk/workflow.py
WorkflowSensorPrimitive Protocol.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from .types import Role, RoomId, SensorEvent, SensorId

@dataclass(frozen=True)
class WorkflowStep:
    step_id:            str
    label:              str
    description:        str
    required_role:      Optional[Role]  = None
    form_schema:        Optional[Dict]  = None
    max_duration_hours: Optional[int]   = None
    is_terminal:        bool            = False

class WorkflowInstanceStatus(str, Enum):
    ACTIVE    = "active"
    COMPLETE  = "complete"
    CANCELLED = "cancelled"
    STALLED   = "stalled"

@dataclass(frozen=True)
class WorkflowStepRecord:
    step_id:     str
    advanced_by: Any
    advanced_at: datetime
    payload:     Dict[str, Any]
    notes:       str

@dataclass(frozen=True)
class WorkflowInstance:
    instance_id:     str
    workflow_id:     str
    room_id:         RoomId
    title:           str
    current_step_id: str
    initiated_by:    Any
    started_at:      datetime
    step_history:    tuple
    status:          WorkflowInstanceStatus = WorkflowInstanceStatus.ACTIVE

@dataclass(frozen=True)
class CrossRoomTrigger:
    on_step_id:     str
    target_room_id: RoomId
    event_type:     str
    payload_fields: tuple = field(default_factory=tuple)

@runtime_checkable
class WorkflowSensorPrimitive(Protocol):
    sensor_id:   SensorId
    room_id:     RoomId
    label:       str
    workflow_id: str
    steps:       List[WorkflowStep]
    def create_instance(self, title: str, initiated_by: Any, room_api: Any,
                        initial_payload: Optional[Dict[str, Any]] = None) -> WorkflowInstance: ...
    def advance_step(self, instance_id: str, advanced_by: Any, room_api: Any,
                     payload: Optional[Dict[str, Any]] = None, notes: str = "") -> WorkflowInstance: ...
    def cancel_instance(self, instance_id: str, cancelled_by: Any, reason: str, room_api: Any) -> WorkflowInstance: ...
    def get_instance(self, instance_id: str, room_api: Any) -> WorkflowInstance: ...
    def list_instances(self, room_api: Any, status: Optional[WorkflowInstanceStatus] = None) -> List[WorkflowInstance]: ...
    def get_stalled_instances(self, as_of: datetime, room_api: Any) -> List[WorkflowInstance]: ...
    def get_instances_at_step(self, step_id: str, room_api: Any) -> List[WorkflowInstance]: ...
    def on_step_complete(self, instance: WorkflowInstance, completed_step: WorkflowStep, room_api: Any) -> None: ...
    def on_workflow_complete(self, instance: WorkflowInstance, room_api: Any) -> None: ...
    def get_cross_room_triggers(self, step_id: str) -> List[CrossRoomTrigger]: ...
    def get_schema(self) -> Dict[str, Any]: ...
    def validate(self, payload: Dict[str, Any]) -> bool: ...
    def on_submit(self, event: SensorEvent, room_api: Any) -> None: ...
