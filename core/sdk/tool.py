"""
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
