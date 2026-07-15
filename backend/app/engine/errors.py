"""Engine-specific exceptions.

Kept separate so later phases (WebSocket layer) can catch engine errors
as a family and translate them into client-facing error messages.
"""


class EngineError(Exception):
    """Base class for all engine errors."""


class InvalidSetupError(EngineError):
    """Raised when a game is constructed with an impossible configuration."""


class OutOfTurnError(EngineError):
    """Raised when a player acts outside of their turn.

    Carries the two ids structurally rather than only baked into the
    message: the engine deals in player ids and has no idea what anyone is
    called, so the server layer needs the raw ids to render a message with
    display names in it. The str() form stays id-based for logs and tests.
    """

    def __init__(self, current_player_id: str, actor_id: str):
        self.current_player_id = current_player_id
        self.actor_id = actor_id
        super().__init__(f"It is {current_player_id}'s turn, not {actor_id}'s")


class IllegalMoveError(EngineError):
    """Raised when a player attempts an action the rules forbid."""
