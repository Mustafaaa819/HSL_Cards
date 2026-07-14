"""Pure-Python core game engine — no FastAPI, no WebSockets, no I/O."""

from .cards import (
    CARDS_PER_PLAYER,
    POWER_RANKS,
    RANK_VALUES,
    RANKS,
    SEVEN_CAP,
    SUITS,
    Card,
    build_deck,
    decks_required,
)
from .errors import EngineError, IllegalMoveError, InvalidSetupError, OutOfTurnError
from .game import FlipResult, Game, Layer, Phase, PlayResult
from .player import Player

__all__ = [
    "CARDS_PER_PLAYER",
    "POWER_RANKS",
    "RANK_VALUES",
    "RANKS",
    "SEVEN_CAP",
    "SUITS",
    "Card",
    "build_deck",
    "decks_required",
    "EngineError",
    "IllegalMoveError",
    "InvalidSetupError",
    "OutOfTurnError",
    "FlipResult",
    "Game",
    "Layer",
    "Phase",
    "PlayResult",
    "Player",
]
