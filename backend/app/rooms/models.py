"""Room state containers — plain data, no HTTP and no game rules.

MAX_PLAYERS is derived from the engine's own constants (two decks is the
hard ceiling per RULES.md) rather than hardcoding 11, so a future rule
change in the engine propagates here automatically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from app.engine import CARDS_PER_PLAYER, RANKS, SUITS, Game

MAX_DECKS = 2
MAX_PLAYERS = (MAX_DECKS * len(SUITS) * len(RANKS)) // CARDS_PER_PLAYER  # = 11
MIN_PLAYERS_TO_START = 2


class RoomStatus(Enum):
    LOBBY = "lobby"
    IN_PROGRESS = "in_progress"


@dataclass
class RoomPlayer:
    player_id: str  # public identifier, also used as the engine player id
    name: str
    token: str  # secret — never included in room state sent to clients
    ready: bool = False
    is_host: bool = False


@dataclass
class Room:
    code: str
    players: list[RoomPlayer] = field(default_factory=list)
    status: RoomStatus = RoomStatus.LOBBY
    game: Game | None = None
    created_at: float = field(default_factory=time.time)
    # Public in-game chat, oldest → newest, capped at CHAT_LOG_LIMIT (see
    # routers.game_ws). Kept on the room, not a socket, so a player who
    # reconnects — or connects late — isn't dropped into a silent table.
    # In memory only, like everything else in this prototype.
    chat_log: list[dict] = field(default_factory=list)

    @property
    def started(self) -> bool:
        return self.status is RoomStatus.IN_PROGRESS

    def public_state(self) -> dict:
        """The lobby view every member may see. Tokens stay out; ready flags
        and host status are public information inside a room."""
        return {
            "code": self.code,
            "status": self.status.value,
            "max_players": MAX_PLAYERS,
            "players": [
                {
                    "player_id": p.player_id,
                    "name": p.name,
                    "ready": p.ready,
                    "is_host": p.is_host,
                }
                for p in self.players
            ],
        }
