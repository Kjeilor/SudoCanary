"""
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
