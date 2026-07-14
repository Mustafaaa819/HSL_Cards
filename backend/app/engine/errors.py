"""Engine-specific exceptions.

Kept separate so later phases (WebSocket layer) can catch engine errors
as a family and translate them into client-facing error messages.
"""


class EngineError(Exception):
    """Base class for all engine errors."""


class InvalidSetupError(EngineError):
    """Raised when a game is constructed with an impossible configuration."""


class OutOfTurnError(EngineError):
    """Raised when a player acts outside of their turn."""


class IllegalMoveError(EngineError):
    """Raised when a player attempts an action the rules forbid."""
