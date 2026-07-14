"""Shared helpers for building rigged game states.

`Game.from_state` runs the normal turn-start step, so if you pass a
non-empty draw_deck the current player immediately draws its top card —
set up deck contents with that in mind.
"""

from app.engine import Card, Game, Player


def c(*specs: str) -> list[Card]:
    """Build cards from compact strings: c("7H", "10S", "AC")."""
    return [Card.from_str(spec) for spec in specs]


def card(spec: str) -> Card:
    return Card.from_str(spec)


def make_game(
    hands: dict[str, dict],
    discard: list[str] | None = None,
    draw_deck: list[str] | None = None,
    current: str | None = None,
    direction: int = 1,
    seven_pending: bool = False,
) -> Game:
    """Rig a game. `hands` maps player id -> {"hand": [...], "face_up": [...],
    "blind": [...]} using compact card strings; missing layers are empty."""
    players = []
    for pid, layers in hands.items():
        players.append(
            Player(
                player_id=pid,
                hand=c(*layers.get("hand", [])),
                face_up=c(*layers.get("face_up", [])),
                blind=c(*layers.get("blind", [])),
            )
        )
    ids = [p.player_id for p in players]
    current_index = ids.index(current) if current else 0
    return Game.from_state(
        players=players,
        draw_deck=c(*(draw_deck or [])),
        discard_pile=c(*(discard or [])),
        direction=direction,
        current_index=current_index,
        seven_pending=seven_pending,
    )
