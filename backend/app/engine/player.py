"""Per-player state: the three card layers and finish tracking."""

from __future__ import annotations

from dataclasses import dataclass, field

from .cards import Card


@dataclass
class Player:
    player_id: str
    # Layer 3 — private hand, the default play source.
    hand: list[Card] = field(default_factory=list)
    # Layer 2 — face-up on the table, playable only once the hand is empty.
    face_up: list[Card] = field(default_factory=list)
    # Layer 1 — face-down, unknown even to the owner; flipped blind one at a time.
    blind: list[Card] = field(default_factory=list)
    # 1-based finishing position, assigned when the player empties all layers.
    finish_position: int | None = None

    @property
    def finished(self) -> bool:
        return self.finish_position is not None

    @property
    def total_cards(self) -> int:
        return len(self.hand) + len(self.face_up) + len(self.blind)
