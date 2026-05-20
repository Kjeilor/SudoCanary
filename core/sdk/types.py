"""
core/sdk/types.py
Shared data types for the Sudo Canary SDK.
All types are immutable by convention. Dataclasses use frozen=True.
"""
from __future__ import annotations
import hashlib, json, uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, NewType, Optional, Tuple

RoomId     = NewType("RoomId",     str)
UserId     = NewType("UserId",     str)
SensorId   = NewType("SensorId",   str)
ToolId     = NewType("ToolId",     str)
EventId    = NewType("EventId",    str)
DocumentId = NewType("DocumentId", str)
TaskId     = NewType("TaskId",     str)

def new_id() -> str:
    return str(uuid.uuid4())

class Role(str, Enum):
    ADMIN         = "admin"
    ANALYST       = "analyst"
    FIELD_OFFICER = "field_officer"
    VIEWER        = "viewer"

@dataclass(frozen=True)
class Member:
    user_id:   UserId
    role:      Role
    joined_at: datetime

@dataclass(frozen=True)
class Room:
    room_id:     RoomId
    name:        str
    description: str
    created_at:  datetime
    members:     Tuple[Member, ...]

@dataclass(frozen=True)
class SensorEvent:
    event_id:   EventId
    room_id:    RoomId
    sensor_id:  SensorId
    user_id:    UserId
    timestamp:  datetime
    payload:    Dict[str, Any]
    provenance: str

    @staticmethod
    def compute_provenance(payload: Dict[str, Any], user_id: UserId, timestamp: datetime) -> str:
        raw = json.dumps({"payload": payload, "user_id": user_id, "timestamp": timestamp.isoformat()}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def verify_provenance(self) -> bool:
        return self.provenance == SensorEvent.compute_provenance(self.payload, self.user_id, self.timestamp)

class ActionType(str, Enum):
    ROOM_CREATED           = "room_created"
    MEMBER_ADDED           = "member_added"
    MEMBER_REMOVED         = "member_removed"
    TASK_CREATED           = "task_created"
    TASK_ASSIGNED          = "task_assigned"
    TASK_PROGRESSED        = "task_progressed"
    TASK_COMPLETED         = "task_completed"
    SENSOR_SUBMITTED       = "sensor_submitted"
    DOCUMENT_UPLOADED      = "document_uploaded"
    DOCUMENT_VERSIONED     = "document_versioned"
    TOOL_INSTALLED         = "tool_installed"
    TOOL_UNINSTALLED       = "tool_uninstalled"
    PERMISSION_GRANTED     = "permission_granted"
    PERMISSION_REVOKED     = "permission_revoked"
    QA_SIGNED_OFF          = "qa_signed_off"
    QA_SUPERSEDED          = "qa_superseded"
    WORKFLOW_STARTED       = "workflow_started"
    WORKFLOW_STEP_ADVANCED = "workflow_step_advanced"
    WORKFLOW_COMPLETED     = "workflow_completed"
    WORKFLOW_CANCELLED     = "workflow_cancelled"
    WORKFLOW_STALLED       = "workflow_stalled"

@dataclass(frozen=True)
class AuditEvent:
    event_id:    EventId
    room_id:     RoomId
    user_id:     UserId
    action_type: ActionType
    timestamp:   datetime
    detail:      Dict[str, Any]

class TaskStatus(str, Enum):
    OPEN        = "open"
    IN_PROGRESS = "in_progress"
    COMPLETE    = "complete"
    OVERDUE     = "overdue"

class TaskTrackability(str, Enum):
    TRACKABLE   = "trackable"
    UNTRACKABLE = "untrackable"

@dataclass(frozen=True)
class Task:
    task_id:      TaskId
    room_id:      RoomId
    title:        str
    description:  str
    created_by:   UserId
    created_at:   datetime
    trackability: TaskTrackability
    assigned_to:  Optional[UserId]  = None
    due_at:       Optional[datetime] = None
    status:       TaskStatus         = TaskStatus.OPEN

@dataclass(frozen=True)
class DocumentVersion:
    version:     int
    uploaded_by: UserId
    uploaded_at: datetime
    file_path:   str
    checksum:    str
    notes:       str

@dataclass(frozen=True)
class Document:
    document_id: DocumentId
    room_id:     RoomId
    name:        str
    versions:    Tuple[DocumentVersion, ...]

    @property
    def current_version(self) -> Optional[DocumentVersion]:
        return self.versions[-1] if self.versions else None

CanaryStatus = Literal["green", "amber", "red", "grey"]

@dataclass(frozen=True)
class CanaryOutput:
    key:        str
    label:      str
    value:      Any
    status:     CanaryStatus
    updated_at: datetime
    detail:     Optional[str] = None

@dataclass(frozen=True)
class CanaryState:
    room_id:      RoomId
    generated_at: datetime
    outputs:      Tuple[CanaryOutput, ...]
    tool_id:      Optional[ToolId] = None

    def get_output(self, key: str) -> Optional[CanaryOutput]:
        return next((o for o in self.outputs if o.key == key), None)

    def outputs_by_status(self, status: CanaryStatus) -> List[CanaryOutput]:
        return [o for o in self.outputs if o.status == status]
