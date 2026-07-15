"""Lobby/room system — sits on top of the Phase 1 engine, owns no game rules."""

from .errors import (
    CannotStartError,
    InvalidTokenError,
    NameTakenError,
    NotHostError,
    RoomAlreadyStartedError,
    RoomError,
    RoomFullError,
    RoomNotFoundError,
)
from .manager import CODE_ALPHABET, CODE_LENGTH, RoomManager, room_manager
from .models import MAX_PLAYERS, MIN_PLAYERS_TO_START, Room, RoomPlayer, RoomStatus

__all__ = [
    "CODE_ALPHABET",
    "CODE_LENGTH",
    "MAX_PLAYERS",
    "MIN_PLAYERS_TO_START",
    "CannotStartError",
    "InvalidTokenError",
    "NameTakenError",
    "NotHostError",
    "Room",
    "RoomAlreadyStartedError",
    "RoomError",
    "RoomFullError",
    "RoomManager",
    "RoomNotFoundError",
    "RoomPlayer",
    "RoomStatus",
    "room_manager",
]
