"""
SDK primitive: NoticeBoard built-in.

Available in every room by default.
Writable by Admin and Officer. Readable by all roles including Viewer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from core.sdk.types import RoomId, UserId  # NewTypes defined in Day 1


@dataclass(frozen=True)
class Notice:
    notice_id: str
    room_id: RoomId
    author_id: UserId
    title: str
    body: str
    created_at: datetime
    pinned: bool = False


class NoticeBoardPrimitive(Protocol):
    """
    Built-in notice board primitive, instantiated per room.

    Access rules enforced by caller via RBAC before calling these methods:
      - post_notice: Admin or Officer only
      - pin_notice:  Admin or Officer only
      - delete_notice: Admin or Officer only
      - get_notices: any role with room access
    """

    def post_notice(
        self,
        room_id: RoomId,
        author_id: UserId,
        title: str,
        body: str,
        pinned: bool = False,
    ) -> Notice: ...

    def get_notices(
        self,
        room_id: RoomId,
        limit: int = 50,
        pinned_first: bool = True,
    ) -> Sequence[Notice]: ...

    def pin_notice(
        self,
        room_id: RoomId,
        notice_id: str,
        pinned: bool,
    ) -> Notice: ...

    def delete_notice(
        self,
        room_id: RoomId,
        notice_id: str,
    ) -> None: ...