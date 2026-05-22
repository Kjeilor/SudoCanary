"""
Role-Based Access Control.

System role ADMIN grants Officer-level access in every room.
Room roles are scoped: OFFICER can manage, VIEWER can only read.
NoticeBoard is writable by Admin and Officer; Viewer cannot post.
"""
from __future__ import annotations

from typing import Optional

from core.models.user import User, SystemRole, RoomRole
from core.sdk.types import RoomId


class PermissionDenied(Exception):
    pass


def is_admin(user: User) -> bool:
    return user.system_role == SystemRole.ADMIN


def get_room_role(user: User, room_id: RoomId) -> Optional[RoomRole]:
    """Return effective room role. Admins receive OFFICER everywhere."""
    if is_admin(user):
        return RoomRole.OFFICER
    return user.room_roles.get(room_id)


def require_room_access(user: User, room_id: RoomId) -> None:
    if get_room_role(user, room_id) is None:
        raise PermissionDenied(
            f"User '{user.username}' has no access to room '{room_id}'"
        )


def require_officer(user: User, room_id: RoomId) -> None:
    if get_room_role(user, room_id) != RoomRole.OFFICER:
        raise PermissionDenied(
            f"User '{user.username}' requires Officer role in room '{room_id}'"
        )


def require_admin(user: User) -> None:
    if not is_admin(user):
        raise PermissionDenied(
            f"User '{user.username}' requires system Admin role"
        )


# Convenience predicates used by built-ins

def can_post_notice(user: User, room_id: RoomId) -> bool:
    return get_room_role(user, room_id) == RoomRole.OFFICER or is_admin(user)


def can_manage_room(user: User, room_id: RoomId) -> bool:
    return is_admin(user) or get_room_role(user, room_id) == RoomRole.OFFICER


def can_read_room(user: User, room_id: RoomId) -> bool:
    return get_room_role(user, room_id) is not None