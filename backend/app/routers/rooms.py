"""REST endpoints for the lobby: create/join/ready/leave/start.

Thin translation layer only — every rule about who may do what lives in
app.rooms.manager. Handlers are async and the manager never awaits, so
each lobby operation runs atomically on the event loop.

Auth model: creating or joining a room returns a secret bearer token, and
every subsequent call proves identity via the X-Player-Token header.
"""

from contextlib import contextmanager
from typing import Iterator

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, field_validator

from app.rooms import (
    CannotStartError,
    InvalidTokenError,
    NameTakenError,
    NotHostError,
    RoomAlreadyStartedError,
    RoomError,
    RoomFullError,
    RoomNotFoundError,
    room_manager,
)

router = APIRouter(prefix="/rooms", tags=["rooms"])

_ERROR_STATUS: dict[type[RoomError], int] = {
    RoomNotFoundError: status.HTTP_404_NOT_FOUND,
    InvalidTokenError: status.HTTP_401_UNAUTHORIZED,
    NotHostError: status.HTTP_403_FORBIDDEN,
    RoomFullError: status.HTTP_409_CONFLICT,
    RoomAlreadyStartedError: status.HTTP_409_CONFLICT,
    NameTakenError: status.HTTP_409_CONFLICT,
    CannotStartError: status.HTTP_409_CONFLICT,
}


@contextmanager
def _room_errors() -> Iterator[None]:
    try:
        yield
    except RoomError as err:
        raise HTTPException(_ERROR_STATUS[type(err)], detail=str(err)) from err


class PlayerNameBody(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not 1 <= len(cleaned) <= 20:
            raise ValueError("Name must be 1-20 characters")
        return cleaned


class ReadyBody(BaseModel):
    ready: bool


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_room(body: PlayerNameBody) -> dict:
    room, host = room_manager.create_room(body.name)
    return {
        "room_code": room.code,
        "player_id": host.player_id,
        "token": host.token,
        "room": room.public_state(),
    }


@router.post("/{code}/join")
async def join_room(code: str, body: PlayerNameBody) -> dict:
    with _room_errors():
        room, player = room_manager.join_room(code, body.name)
    return {
        "room_code": room.code,
        "player_id": player.player_id,
        "token": player.token,
        "room": room.public_state(),
    }


@router.post("/{code}/reclaim")
async def reclaim_player(code: str, body: PlayerNameBody) -> dict:
    """Rejoin an already-started game by name — same response shape as join,
    so the frontend treats a reclaim result identically to a fresh join."""
    with _room_errors():
        room, player = room_manager.reclaim_player(code, body.name)
    return {
        "room_code": room.code,
        "player_id": player.player_id,
        "token": player.token,
        "room": room.public_state(),
    }


@router.get("/{code}")
async def get_room(code: str, x_player_token: str = Header()) -> dict:
    with _room_errors():
        room = room_manager.get_room(code)
        room_manager.authenticate(room, x_player_token)  # members only
    return room.public_state()


@router.put("/{code}/ready")
async def set_ready(code: str, body: ReadyBody, x_player_token: str = Header()) -> dict:
    with _room_errors():
        room, _player = room_manager.set_ready(code, x_player_token, body.ready)
    return room.public_state()


@router.post("/{code}/leave")
async def leave_room(code: str, x_player_token: str = Header()) -> dict:
    with _room_errors():
        room = room_manager.leave_room(code, x_player_token)
    return {"left": True, "room": room.public_state() if room else None}


@router.post("/{code}/start")
async def start_game(code: str, x_player_token: str = Header()) -> dict:
    with _room_errors():
        room = room_manager.start_game(code, x_player_token)
    return room.public_state()
