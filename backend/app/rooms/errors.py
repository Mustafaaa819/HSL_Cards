"""Room/lobby exceptions.

Same pattern as the engine's error family: the manager raises these, and
the REST router translates them into HTTP status codes. Keeping them
HTTP-free means Phase 3 can reuse the manager over WebSockets unchanged.
"""


class RoomError(Exception):
    """Base class for all room/lobby errors."""


class RoomNotFoundError(RoomError):
    """No room exists with the given code."""


class RoomFullError(RoomError):
    """The room is at the engine's maximum player count."""


class RoomAlreadyStartedError(RoomError):
    """The action is only valid while the room is still in the lobby."""


class NameTakenError(RoomError):
    """Another player in the room already uses this name."""


class InvalidTokenError(RoomError):
    """The supplied player token doesn't belong to anyone in this room."""


class NotHostError(RoomError):
    """The action is reserved for the room's host."""


class CannotStartError(RoomError):
    """Start conditions not met (too few players, or not everyone ready)."""
