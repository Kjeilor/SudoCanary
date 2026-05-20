"""
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
