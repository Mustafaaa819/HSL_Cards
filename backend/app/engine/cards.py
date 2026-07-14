"""Card and deck primitives.

Rank ordering follows RULES.md: 2 low through Ace high. The 2, 7, 10 and J
are power cards; their power behaviour lives in the game engine — here they
are just flagged so validation can special-case them.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .errors import InvalidSetupError

SUITS: tuple[str, ...] = ("C", "D", "H", "S")

RANKS: tuple[str, ...] = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")

# Ace is high. 2 is the lowest value, which makes a played 2 "reset" the pile
# naturally: any card beats it under the normal higher-than rule.
RANK_VALUES: dict[str, int] = {rank: index + 2 for index, rank in enumerate(RANKS)}

POWER_RANKS: frozenset[str] = frozenset({"2", "7", "10", "J"})

# The 7 "under-power" cap: the constrained player may only play value <= 7.
SEVEN_CAP: int = 7

CARDS_PER_PLAYER: int = 9  # 3 layers x 3 cards
SINGLE_DECK_MAX_PLAYERS: int = 5  # per RULES.md: 6+ players switches to two decks


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    def __post_init__(self) -> None:
        if self.rank not in RANK_VALUES:
            raise ValueError(f"Unknown rank: {self.rank!r}")
        if self.suit not in SUITS:
            raise ValueError(f"Unknown suit: {self.suit!r}")

    @property
    def value(self) -> int:
        return RANK_VALUES[self.rank]

    @property
    def is_power(self) -> bool:
        return self.rank in POWER_RANKS

    @classmethod
    def from_str(cls, text: str) -> "Card":
        # "10H" is the only 3-char form, so rank is everything but the last char.
        return cls(rank=text[:-1], suit=text[-1])

    def __repr__(self) -> str:
        return f"{self.rank}{self.suit}"


def decks_required(num_players: int) -> int:
    return 1 if num_players <= SINGLE_DECK_MAX_PLAYERS else 2


def build_deck(num_players: int, rng: random.Random | None = None) -> list[Card]:
    """Build the shuffled draw deck(s) for the given player count."""
    if num_players < 2:
        raise InvalidSetupError("At least 2 players are required")

    num_decks = decks_required(num_players)
    total_cards = num_decks * len(SUITS) * len(RANKS)
    if num_players * CARDS_PER_PLAYER > total_cards:
        raise InvalidSetupError(
            f"{num_players} players need {num_players * CARDS_PER_PLAYER} cards "
            f"but {num_decks} deck(s) only hold {total_cards}"
        )

    cards = [
        Card(rank, suit)
        for _ in range(num_decks)
        for suit in SUITS
        for rank in RANKS
    ]
    (rng or random.Random()).shuffle(cards)
    return cards
