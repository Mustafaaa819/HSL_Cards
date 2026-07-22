"""In-memory room store and all lobby state transitions.

Storage is a plain dict of room code -> Room, which is enough for the
prototype (single process, no persistence across restarts). All methods
are synchronous and never await, so as long as the HTTP/WS layer calls
them from async handlers on the single event loop, each operation is
atomic — no locking needed yet.
"""

from __future__ import annotations

import secrets

from app.engine import Game

from .errors import (
    CannotStartError,
    InvalidTokenError,
    NameTakenError,
    NotHostError,
    RoomAlreadyStartedError,
    RoomFullError,
    RoomNotFoundError,
)
from .models import MAX_PLAYERS, MIN_PLAYERS_TO_START, Room, RoomPlayer, RoomStatus

# Room-code alphabet: no 0/O, 1/I/L so codes survive being read aloud or
# typed from a friend's message. 5 chars over 31 symbols ≈ 28.6M codes.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 5


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}

    def reset(self) -> None:
        """Drop all rooms — test isolation between cases."""
        self._rooms.clear()

    # ------------------------------------------------------------------ lookup

    def get_room(self, code: str) -> Room:
        room = self._rooms.get(code.upper())
        if room is None:
            raise RoomNotFoundError(f"No room with code {code.upper()}")
        return room

    def authenticate(self, room: Room, token: str) -> RoomPlayer:
        for player in room.players:
            if secrets.compare_digest(player.token, token):
                return player
        raise InvalidTokenError("Token does not belong to any player in this room")

    # ----------------------------------------------------------------- actions

    def create_room(self, host_name: str) -> tuple[Room, RoomPlayer]:
        room = Room(code=self._new_code())
        host = self._make_player(host_name, is_host=True)
        room.players.append(host)
        self._rooms[room.code] = room
        return room, host

    def join_room(self, code: str, name: str) -> tuple[Room, RoomPlayer]:
        room = self.get_room(code)
        if room.started:
            raise RoomAlreadyStartedError("This game has already started")
        if len(room.players) >= MAX_PLAYERS:
            raise RoomFullError(f"Room is full ({MAX_PLAYERS} players max)")
        if any(p.name.casefold() == name.casefold() for p in room.players):
            raise NameTakenError(f"Someone in this room is already called {name!r}")
        player = self._make_player(name)
        room.players.append(player)
        return room, player

    def reclaim_player(self, code: str, name: str) -> tuple[Room, RoomPlayer]:
        """Hand a disconnected player back their own seat by name match.

        Only valid once the game has started — a not-yet-started room's lobby
        already has a normal join flow for this. Identity is proven by room
        code + the exact (case-insensitive) name they joined with, matching
        the uniqueness `join_room` enforces; no separate per-player secret.
        The player's token was never invalidated (nothing here revokes one),
        so this mints nothing new, it just looks the existing seat back up.
        Reuses the existing "you don't have access" error shapes rather than
        inventing new ones: not-started → RoomNotFoundError, unknown name →
        InvalidTokenError, both already mapped for the frontend.
        """
        room = self.get_room(code)
        if not room.started:
            raise RoomNotFoundError("This room hasn't started yet — use join instead")
        for player in room.players:
            if player.name.casefold() == name.casefold():
                return room, player
        raise InvalidTokenError(f"No player named {name!r} in this room")

    def set_ready(self, code: str, token: str, ready: bool) -> tuple[Room, RoomPlayer]:
        room = self.get_room(code)
        if room.started:
            raise RoomAlreadyStartedError("The game has already started")
        player = self.authenticate(room, token)
        player.ready = ready
        return room, player

    def leave_room(self, code: str, token: str) -> Room | None:
        """Remove a player from a not-yet-started room. Returns the room, or
        None if it emptied and was deleted. Host leaving passes host to the
        earliest remaining joiner."""
        room = self.get_room(code)
        if room.started:
            # Mid-game departure is a disconnect/reconnect problem for the
            # Phase 3 WebSocket layer, not a lobby action.
            raise RoomAlreadyStartedError("Cannot leave a started game via the lobby")
        player = self.authenticate(room, token)
        room.players.remove(player)
        if not room.players:
            del self._rooms[room.code]
            return None
        if player.is_host:
            room.players[0].is_host = True
        return room

    def start_game(self, code: str, token: str) -> Room:
        room = self.get_room(code)
        if room.started:
            raise RoomAlreadyStartedError("The game has already started")
        player = self.authenticate(room, token)
        if not player.is_host:
            raise NotHostError("Only the host can start the game")
        if len(room.players) < MIN_PLAYERS_TO_START:
            raise CannotStartError(f"Need at least {MIN_PLAYERS_TO_START} players to start")
        not_ready = [p.name for p in room.players if not p.ready]
        if not_ready:
            raise CannotStartError(f"Not everyone is ready: {', '.join(not_ready)}")

        # Join order is seat order — seat 0 (the host) starts, per RULES.md.
        room.game = Game([p.player_id for p in room.players])
        room.status = RoomStatus.IN_PROGRESS
        return room

    # ---------------------------------------------------------------- internal

    def _new_code(self) -> str:
        for _ in range(100):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._rooms:
                return code
        # 100 straight collisions means the code space is effectively spent.
        raise RuntimeError("Could not allocate a unique room code")

    def _make_player(self, name: str, is_host: bool = False) -> RoomPlayer:
        return RoomPlayer(
            player_id=secrets.token_hex(4),
            name=name,
            token=secrets.token_urlsafe(16),
            is_host=is_host,
        )


# Single shared instance for the app's lifetime. Tests construct their own
# or clear this one between cases.
room_manager = RoomManager()
