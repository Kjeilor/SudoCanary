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
TemplateId = NewType("TemplateId", str)
BypassId   = NewType("BypassId",   str)
InstanceId = NewType("InstanceId", str)

def new_id() -> str:
    return str(uuid.uuid4())

class Role(str, Enum):
    # System-level roles
    ORCHESTRATOR  = "orchestrator"  # maps institution, creates rooms, approves processes
    AUDITOR       = "auditor"       # read-only across designated rooms, no interaction
    DATA_OFFICER  = "data_officer"  # DPPA compliance role, data inventory and retention
    # Room-level roles
    ADMIN         = "admin"         # full room control, tool install/uninstall
    APPROVER      = "approver"      # gates workflow approval steps, no other room access
    ANALYST       = "analyst"       # read all, submit forms, generate reports
    FIELD_OFFICER = "field_officer" # submit sensors, view own tasks, photo check-ins
    VIEWER        = "viewer"        # read-only, no submission

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
    WORKFLOW_BYPASSED           = "workflow_bypassed"
    WORKFLOW_ESCALATED          = "workflow_escalated"
    WORKFLOW_TEMPLATE_CREATED   = "workflow_template_created"
    WORKFLOW_TEMPLATE_PUBLISHED = "workflow_template_published"
    WORKFLOW_TEMPLATE_ARCHIVED  = "workflow_template_archived"

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


# ---------------------------------------------------------------------------
# Workflow template building blocks
# ---------------------------------------------------------------------------

class TemplateStatus(str, Enum):
    DRAFT     = "draft"      # being built, cannot be instantiated
    PUBLISHED = "published"  # live, can be instantiated
    ARCHIVED  = "archived"   # frozen, existing instances complete, no new ones


class TemplateScope(str, Enum):
    ROOM   = "room"    # available only within the owning room
    SYSTEM = "system"  # available across all rooms (Orchestrator-created)


@dataclass(frozen=True)
class StepRouting:
    """
    Defines where a workflow instance moves after a step completes.
    Attached to a WorkflowStep to express non-linear routing.

    on_approve:   step_id to advance to on a positive outcome
    on_reject:    step_id to advance to on a negative outcome
    on_condition: dict mapping a form field value to a step_id
                  e.g. {"urgency": {"high": "fast_track", "low": "standard"}}
    Default (all None): advance to the next step in sequence.
    """
    on_approve:   Optional[str]            = None
    on_reject:    Optional[str]            = None
    on_condition: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class BypassRule:
    """
    A named override that lets authorised users intervene in a running
    workflow instance at any point, regardless of the current step.

    A bypass is not a flaw in the process — it is a documented deviation.
    requires_reason is always enforced. The intervention is written to
    the instance's intervention_log and to the immutable audit trail.

    target_step_id: where the instance moves to. None = outright cancellation.
    notifies:       roles or UserIds informed when this bypass fires.
    """
    bypass_id:       BypassId
    label:           str
    permitted_roles: Tuple[Role, ...]
    permitted_users: Tuple[str, ...]       # UserIds, empty = role-only
    target_step_id:  Optional[str]         # None = cancel the instance
    requires_reason: bool                  = True
    notifies:        Tuple[str, ...]       = ()  # role values or UserIds


@dataclass(frozen=True)
class EscalationRule:
    """
    Defines what happens when a step stalls past its SLA window.

    Escalation does not skip steps — it reassigns decision authority.
    after_hours:          hours past the step SLA before first escalation
    notify:               who is notified first (role value or UserId)
    reassign_to_role:     if unresolved after a second window, reassign here
    second_window_hours:  additional hours before reassignment fires
    final_escalation_to:  last stop. If unresolved, instance is STALLED permanently.
    """
    on_step_id:          str
    after_hours:         int
    notify:              str               # role value or UserId
    reassign_to_role:    Optional[Role]    = None
    second_window_hours: Optional[int]     = None
    final_escalation_to: Optional[str]     = None  # role value or UserId


@dataclass(frozen=True)
class InterventionRecord:
    """
    Immutable record of a bypass action on a workflow instance.
    Stored in WorkflowInstance.intervention_log, never in step_history.
    The separation makes deviations visible as deviations.
    """
    intervention_id: str
    bypass_id:       BypassId
    triggered_by:    UserId
    triggered_at:    datetime
    from_step_id:    str
    to_step_id:      Optional[str]    # None if instance was cancelled
    reason:          str
    notified:        Tuple[str, ...]  # who was informed


@dataclass(frozen=True)
class EscalationRecord:
    """Immutable record of an escalation event on a workflow instance."""
    escalation_id: str
    on_step_id:    str
    triggered_at:  datetime
    notified:      str
    reassigned_to: Optional[str]      # role value or UserId, None if not yet reassigned


@dataclass(frozen=True)
class TemplateChangelogEntry:
    """One immutable entry in a template's version history."""
    version:    int
    changed_by: UserId
    changed_at: datetime
    notes:      str


@dataclass(frozen=True)
class WorkflowTemplate:
    """
    A stored, named, reusable workflow definition.

    Created by an Orchestrator (system scope) or Admin (room scope).
    Instantiated by users with permitted roles.
    Versioned — active instances run on the version they were started on.
    Only PUBLISHED templates can be instantiated.
    ARCHIVED templates are frozen — no new instances, existing ones complete.

    steps:               ordered. routing on each step overrides linear sequence.
    bypass_rules:        role-gated overrides for non-linear intervention.
    escalation_rules:    SLA breach response chain.
    cross_room_triggers: declared now, activated in Epoch 2.
    """
    template_id:      TemplateId
    name:             str
    version:          int
    status:           TemplateStatus
    scope:            TemplateScope
    created_by:       UserId
    owned_by_room:    Optional[RoomId]           # None = system-level
    steps:            Tuple[Any, ...]            # Tuple[WorkflowStep, ...]
    routing:          Dict[str, StepRouting]     # step_id -> StepRouting
    bypass_rules:     Tuple[BypassRule, ...]
    escalation_rules: Tuple[EscalationRule, ...]
    cross_room_triggers: Tuple[Any, ...]         # Tuple[CrossRoomTrigger, ...]
    required_roles_to_instantiate: Tuple[Role, ...]
    required_roles_to_view:        Tuple[Role, ...]
    changelog:        Tuple[TemplateChangelogEntry, ...]
    published_at:     Optional[datetime]         = None
    last_modified_at: Optional[datetime]         = None