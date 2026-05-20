"""
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
