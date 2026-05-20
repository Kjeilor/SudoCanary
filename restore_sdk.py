"""
restore_sdk.py
Run this from the root of your SudoCanary directory:
    python3 restore_sdk.py
It writes the correct content to all empty SDK files.
"""
import os

files = {}

files["core/sdk/types.py"] = '''"""
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
'''

files["core/sdk/canary.py"] = '''"""
core/sdk/canary.py
CanaryInterface Protocol.
"""
from __future__ import annotations
from typing import Callable, List, Optional, Protocol, runtime_checkable
from .types import CanaryOutput, CanaryState, RoomId, ToolId

@runtime_checkable
class CanaryInterface(Protocol):
    def write_outputs(self, room_id: RoomId, tool_id: ToolId, outputs: List[CanaryOutput]) -> None: ...
    def get_state(self, room_id: RoomId) -> CanaryState: ...
    def subscribe(self, room_id: RoomId, callback: Callable[[CanaryState], None]) -> str: ...
    def unsubscribe(self, subscription_id: str) -> None: ...
'''

files["core/sdk/room.py"] = '''"""
core/sdk/room.py
RoomAPI Protocol.
"""
from __future__ import annotations
from datetime import datetime
from typing import List, Optional, Protocol, runtime_checkable
from .types import (AuditEvent, ActionType, Document, DocumentId, Member,
                    Room, RoomId, SensorEvent, SensorId, Task, TaskId, TaskStatus, UserId)

@runtime_checkable
class RoomAPI(Protocol):
    def get_room(self, room_id: RoomId) -> Room: ...
    def list_rooms(self, user_id: UserId) -> List[Room]: ...
    def get_members(self, room_id: RoomId) -> List[Member]: ...
    def read_sensor_data(self, room_id: RoomId, sensor_id: SensorId,
                         since: Optional[datetime] = None, limit: Optional[int] = None) -> List[SensorEvent]: ...
    def write_sensor_event(self, room_id: RoomId, sensor_id: SensorId,
                           user_id: UserId, payload: dict) -> SensorEvent: ...
    def create_task(self, room_id: RoomId, created_by: UserId, title: str,
                    description: str, assigned_to: Optional[UserId] = None,
                    due_at: Optional[datetime] = None) -> Task: ...
    def update_task_status(self, room_id: RoomId, task_id: TaskId,
                           updated_by: UserId, new_status: TaskStatus) -> Task: ...
    def list_tasks(self, room_id: RoomId, status: Optional[TaskStatus] = None) -> List[Task]: ...
    def get_task(self, room_id: RoomId, task_id: TaskId) -> Task: ...
    def upload_document(self, room_id: RoomId, uploaded_by: UserId,
                        name: str, file_path: str, notes: str = "") -> Document: ...
    def get_document(self, room_id: RoomId, document_id: DocumentId) -> Document: ...
    def list_documents(self, room_id: RoomId) -> List[Document]: ...
    def get_audit_trail(self, room_id: RoomId, since: Optional[datetime] = None,
                        action_types: Optional[List[ActionType]] = None) -> List[AuditEvent]: ...
'''

files["core/sdk/sensor.py"] = '''"""
core/sdk/sensor.py
Sensor primitives.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from .types import RoomId, SensorEvent, SensorId

@runtime_checkable
class SensorPrimitive(Protocol):
    sensor_id: SensorId
    room_id:   RoomId
    label:     str
    def get_schema(self) -> Dict[str, Any]: ...
    def validate(self, payload: Dict[str, Any]) -> bool: ...
    def on_submit(self, event: SensorEvent, room_api: Any) -> None: ...

@runtime_checkable
class FormSensorPrimitive(Protocol):
    sensor_id: SensorId
    room_id:   RoomId
    label:     str
    schema:    Dict[str, Any]
    def get_schema(self) -> Dict[str, Any]: ...
    def validate(self, payload: Dict[str, Any]) -> bool: ...
    def on_submit(self, event: SensorEvent, room_api: Any) -> None: ...

@runtime_checkable
class QRTriggerPrimitive(Protocol):
    sensor_id: SensorId
    room_id:   RoomId
    label:     str
    def generate_qr(self, entity_id: str) -> bytes: ...
    def decode_qr(self, qr_data: str) -> Dict[str, Any]: ...
    def on_scan(self, qr_data: str, room_api: Any) -> SensorEvent: ...
    def get_schema(self) -> Dict[str, Any]: ...
    def validate(self, payload: Dict[str, Any]) -> bool: ...
    def on_submit(self, event: SensorEvent, room_api: Any) -> None: ...

@runtime_checkable
class DocumentSensorPrimitive(Protocol):
    sensor_id:          SensorId
    room_id:            RoomId
    label:              str
    allowed_extensions: List[str]
    max_file_size_mb:   float
    def validate(self, payload: Dict[str, Any]) -> bool: ...
    def on_upload(self, event: SensorEvent, room_api: Any) -> None: ...
    def get_schema(self) -> Dict[str, Any]: ...
    def on_submit(self, event: SensorEvent, room_api: Any) -> None: ...
    def get_versions(self, document_id: str, room_api: Any) -> List[Any]: ...

@runtime_checkable
class PhotoCheckInPrimitive(Protocol):
    sensor_id:             SensorId
    room_id:               RoomId
    label:                 str
    stale_threshold_hours: int
    def on_checkin(self, entity_id: str, photo_bytes: bytes, user_id: Any,
                   room_api: Any, gps_lat: Optional[float] = None, gps_lon: Optional[float] = None) -> SensorEvent: ...
    def get_last_checkin(self, entity_id: str, room_api: Any) -> Optional[SensorEvent]: ...
    def get_stale_entities(self, entity_ids: List[str], as_of: datetime, room_api: Any) -> List[str]: ...
    def get_schema(self) -> Dict[str, Any]: ...
    def validate(self, payload: Dict[str, Any]) -> bool: ...
    def on_submit(self, event: SensorEvent, room_api: Any) -> None: ...
'''

files["core/sdk/visualisation.py"] = '''"""
core/sdk/visualisation.py
Visualisation hooks.
"""
from __future__ import annotations
from typing import Any, List, Optional, Protocol, runtime_checkable
from .types import CanaryState, RoomId

@runtime_checkable
class VisualisationPanel(Protocol):
    panel_id: str
    label:    str
    room_id:  RoomId
    def create_widget(self, canary_state: CanaryState) -> Any: ...
    def on_canary_update(self, canary_state: CanaryState) -> None: ...

@runtime_checkable
class VisualisationRegistry(Protocol):
    def register_panel(self, panel: VisualisationPanel) -> None: ...
    def unregister_panel(self, panel_id: str, room_id: RoomId) -> None: ...
    def get_panel(self, panel_id: str, room_id: RoomId) -> Optional[VisualisationPanel]: ...
    def list_panels(self, room_id: RoomId) -> List[str]: ...
'''

files["core/sdk/permissions.py"] = '''"""
core/sdk/permissions.py
Permissions model.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Protocol, runtime_checkable
from .types import RoomId, ToolId, UserId

class Action:
    READ_ROOM            = "read_room"
    LIST_MEMBERS         = "list_members"
    READ_SENSOR_DATA     = "read_sensor_data"
    WRITE_SENSOR_EVENT   = "write_sensor_event"
    CREATE_TASK          = "create_task"
    UPDATE_TASK_STATUS   = "update_task_status"
    LIST_TASKS           = "list_tasks"
    UPLOAD_DOCUMENT      = "upload_document"
    READ_DOCUMENT        = "read_document"
    READ_AUDIT_TRAIL     = "read_audit_trail"
    WRITE_CANARY_OUTPUTS = "write_canary_outputs"
    READ_CANARY_STATE    = "read_canary_state"
    REGISTER_PANEL       = "register_panel"

@dataclass(frozen=True)
class PermissionsDeclaration:
    tool_id:          ToolId
    required_rooms:   List[RoomId]
    required_actions: List[str]
    optional_actions: List[str]
    justification:    str

@runtime_checkable
class PermissionsModel(Protocol):
    def grant_permissions(self, admin_user_id: UserId, room_id: RoomId, declaration: PermissionsDeclaration) -> None: ...
    def revoke_permissions(self, admin_user_id: UserId, room_id: RoomId, tool_id: ToolId) -> None: ...
    def check_permission(self, tool_id: ToolId, room_id: RoomId, action: str) -> bool: ...
    def get_granted_permissions(self, tool_id: ToolId, room_id: RoomId) -> Optional[PermissionsDeclaration]: ...
'''

files["core/sdk/tool.py"] = '''"""
core/sdk/tool.py
ToolInterface Protocol.
"""
from __future__ import annotations
from typing import List, Protocol, runtime_checkable
from .canary import CanaryInterface
from .permissions import PermissionsDeclaration, PermissionsModel
from .room import RoomAPI
from .sensor import SensorPrimitive
from .types import RoomId, ToolId
from .visualisation import VisualisationRegistry

@runtime_checkable
class ToolInterface(Protocol):
    tool_id:      ToolId
    tool_name:    str
    tool_version: str
    description:  str
    def get_permissions(self) -> PermissionsDeclaration: ...
    def install(self, room_ids: List[RoomId], room_api: RoomAPI, canary: CanaryInterface,
                viz_registry: VisualisationRegistry, permissions: PermissionsModel) -> None: ...
    def uninstall(self, room_ids: List[RoomId]) -> None: ...
    def get_sensors(self) -> List[SensorPrimitive]: ...
'''

files["core/sdk/workflow.py"] = '''"""
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
'''

for path, content in files.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(f"  written: {path}")

print("\nDone. Run the check:")
print('  python3 -c "from core.sdk import ToolInterface, WorkflowSensorPrimitive, CanaryOutput; print(\'OK\')"')