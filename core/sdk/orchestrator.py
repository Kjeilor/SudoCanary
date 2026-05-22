"""
core/sdk/orchestrator.py
-------------------------
OrchestratorAPI Protocol and SystemMap types.

The Orchestrator is the only system-level role. They see and manage the
institution as a whole — not just individual rooms.

SystemMap is the data type that represents the institution as a graph.
Rooms are nodes. Cross-room workflow connections are edges.
Canary status colours each node.

Epoch 1: SystemMap is read-only. The Orchestrator can see the full picture.
Epoch 2: The map becomes editable. Rooms are created by dragging. Workflows
         are connected by drawing edges between rooms.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from .types import (
    CanaryStatus,
    Role,
    RoomId,
    TemplateId,
    ToolId,
    UserId,
    WorkflowTemplate,
)


# ---------------------------------------------------------------------------
# System map types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoomNode:
    """
    A room represented as a node in the system map.

    position_x / position_y: layout coordinates for the visual map.
    canary_status: current overall Canary status for this room.
    active_workflow_count: how many workflow instances are currently running.
    stalled_workflow_count: how many are stalled — drives the visual alert state.
    """
    room_id:                RoomId
    name:                   str
    tool_id:                Optional[ToolId]
    canary_status:          CanaryStatus
    active_workflow_count:  int
    stalled_workflow_count: int
    member_count:           int
    position_x:             float = 0.0
    position_y:             float = 0.0


@dataclass(frozen=True)
class RoomEdge:
    """
    A directed connection between two rooms in the system map.
    Represents an active CrossRoomTrigger between a workflow step
    in source_room and an event received by target_room.

    label: the event_type string from CrossRoomTrigger — human-readable.
    active: True if the trigger has fired at least once. False = declared but unused.
    """
    edge_id:     str
    source_room: RoomId
    target_room: RoomId
    label:       str
    active:      bool = False


@dataclass(frozen=True)
class SystemMap:
    """
    The institution as a graph.

    nodes: all rooms in the system, with their current Canary state.
    edges: cross-room workflow connections between rooms.
    generated_at: timestamp of this snapshot.

    The Orchestrator Dashboard renders this as a visual map.
    Node colour = Canary status (grey/amber/red/green).
    Edge thickness = connection activity.
    Stalled nodes pulse amber in the UI.
    """
    nodes:            Tuple[RoomNode, ...]
    edges:            Tuple[RoomEdge, ...]
    generated_at:     datetime
    institution_name: str


# ---------------------------------------------------------------------------
# OrchestratorAPI Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class OrchestratorAPI(Protocol):
    """
    System-level operations available only to users with Role.ORCHESTRATOR.

    The Orchestrator is the only role that operates outside room boundaries.
    All OrchestratorAPI calls are permission-checked for Role.ORCHESTRATOR
    and logged to the system-level audit trail.
    """

    # ------------------------------------------------------------------
    # System map
    # ------------------------------------------------------------------

    def get_system_map(self) -> SystemMap:
        """
        Return the current system map — all rooms, their Canary state,
        and all active cross-room connections.
        Generates a fresh snapshot on each call.
        """
        ...

    # ------------------------------------------------------------------
    # Room management
    # ------------------------------------------------------------------

    def create_room(
        self,
        name:        str,
        description: str,
        created_by:  UserId,
    ) -> RoomId:
        """
        Create a new room in the system.
        The creating Orchestrator is not automatically a member —
        rooms are owned by their Admin members, not the Orchestrator.
        Logs ROOM_CREATED to the audit trail.
        """
        ...

    def delete_room(
        self,
        room_id:    RoomId,
        deleted_by: UserId,
        reason:     str,
    ) -> None:
        """
        Delete a room. Requires a mandatory reason.
        All room data is archived, not destroyed — DPPA retention compliance.
        Active workflow instances are cancelled with reason logged.
        Logs ROOM_DELETED to the audit trail.
        """
        ...

    # ------------------------------------------------------------------
    # Workflow template management
    # ------------------------------------------------------------------

    def create_template(
        self,
        name:          str,
        created_by:    UserId,
        scope:         Any,                     # TemplateScope
        owned_by_room: Optional[RoomId] = None,
    ) -> WorkflowTemplate:
        """
        Create a new workflow template in DRAFT status.
        Returns the empty template ready for step definition.
        """
        ...

    def publish_template(
        self,
        template_id:  TemplateId,
        published_by: UserId,
    ) -> WorkflowTemplate:
        """
        Publish a DRAFT template. Once published it can be instantiated.
        Logs WORKFLOW_TEMPLATE_PUBLISHED to the audit trail.
        Raises ValueError if the template has no steps or no terminal step.
        """
        ...

    def archive_template(
        self,
        template_id: TemplateId,
        archived_by: UserId,
        reason:      str,
    ) -> WorkflowTemplate:
        """
        Archive a PUBLISHED template. No new instances can be created.
        Existing instances run to completion on their current version.
        Logs WORKFLOW_TEMPLATE_ARCHIVED to the audit trail.
        """
        ...

    def get_template(self, template_id: TemplateId) -> WorkflowTemplate:
        """Return a workflow template by ID."""
        ...

    def list_templates(
        self,
        scope:  Optional[Any] = None,   # TemplateScope filter
        status: Optional[Any] = None,   # TemplateStatus filter
    ) -> List[WorkflowTemplate]:
        """List all templates visible to the Orchestrator."""
        ...

    def install_template_in_room(
        self,
        template_id:  TemplateId,
        room_id:      RoomId,
        installed_by: UserId,
    ) -> None:
        """
        Make a system-scoped template available in a specific room.
        Room members with required_roles_to_instantiate can then
        start instances of it within their room.
        """
        ...

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def get_system_audit_trail(
        self,
        since: Optional[datetime] = None,
    ) -> List[Any]:                     # List[AuditEvent]
        """
        Return the system-level audit trail — all events across all rooms.
        Only the Orchestrator and Auditor can call this.
        """
        ...
