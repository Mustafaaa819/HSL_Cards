"""Core game engine — pure Python, no networking.

The engine is the sole authority on rules. Actions are explicit methods
(`play_card`, `pick_up_pile`, `flip_blind`); illegal actions raise instead
of silently mutating state, so the server layer in later phases can simply
translate exceptions into client error messages.

Turn model: the deck-phase draw ("on your turn, draw one card") carries no
decision, so the engine performs it automatically the moment a player's turn
begins. Every action method then completes the turn and advances play.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from .cards import SEVEN_CAP, Card, build_deck
from .errors import IllegalMoveError, InvalidSetupError, OutOfTurnError
from .player import Player

LAYER_SIZE = 3  # cards per layer at deal time


class Layer(Enum):
    HAND = "hand"
    FACE_UP = "face_up"
    BLIND = "blind"


class Phase(Enum):
    DECK = "deck"  # shared draw deck still has cards
    HAND = "hand"  # deck exhausted — the "real start" per RULES.md


@dataclass
class PlayResult:
    card: Card
    pile_burned: bool = False
    direction_reversed: bool = False
    player_finished: bool = False
    game_over: bool = False


@dataclass
class FlipResult:
    card: Card
    played: bool  # True if the flipped card legally beat the pile
    pile_burned: bool = False
    direction_reversed: bool = False
    picked_up: int = 0  # cards taken into hand on a failed flip (pile + the flip)
    player_finished: bool = False
    game_over: bool = False


class Game:
    def __init__(self, player_ids: list[str], rng: random.Random | None = None):
        if len(set(player_ids)) != len(player_ids):
            raise InvalidSetupError("Player ids must be unique")

        self.rng = rng or random.Random()
        deck = build_deck(len(player_ids), self.rng)

        self.players: list[Player] = []
        for pid in player_ids:
            self.players.append(
                Player(
                    player_id=pid,
                    blind=[deck.pop() for _ in range(LAYER_SIZE)],
                    face_up=[deck.pop() for _ in range(LAYER_SIZE)],
                    hand=[deck.pop() for _ in range(LAYER_SIZE)],
                )
            )

        self.draw_deck: list[Card] = deck
        self.discard_pile: list[Card] = []
        self.burned: list[Card] = []  # cards nuked out of the game by a 10
        self.direction: int = 1  # +1 clockwise, -1 counterclockwise (J flips it)
        self.current_index: int = 0
        # True while the current player is under a just-played 7's constraint.
        self.seven_pending: bool = False
        self.finish_order: list[str] = []
        self.game_over: bool = False

        self._start_turn()

    @classmethod
    def from_state(
        cls,
        players: list[Player],
        draw_deck: list[Card] | None = None,
        discard_pile: list[Card] | None = None,
        direction: int = 1,
        current_index: int = 0,
        seven_pending: bool = False,
    ) -> "Game":
        """Build a game from an explicit mid-game state (tests, and later
        server-side restore). Runs the normal turn-start step, so during the
        deck phase the current player immediately draws their card."""
        game = cls.__new__(cls)
        game.rng = random.Random()
        game.players = list(players)
        game.draw_deck = list(draw_deck or [])
        game.discard_pile = list(discard_pile or [])
        game.burned = []
        game.direction = direction
        game.current_index = current_index
        game.seven_pending = seven_pending
        finished = [p for p in game.players if p.finished]
        finished.sort(key=lambda p: p.finish_position)
        game.finish_order = [p.player_id for p in finished]
        game.game_over = False
        game._start_turn()
        return game

    # ------------------------------------------------------------------ views

    @property
    def current_player(self) -> Player:
        return self.players[self.current_index]

    @property
    def top_card(self) -> Card | None:
        return self.discard_pile[-1] if self.discard_pile else None

    @property
    def phase(self) -> Phase:
        return Phase.DECK if self.draw_deck else Phase.HAND

    def active_layer(self, player: Player) -> Layer:
        # While the draw deck lives, the hand is always the active layer:
        # even if it momentarily empties, the turn-start draw refills it,
        # so layer transitions only ever happen in the hand phase.
        if player.hand or self.draw_deck:
            return Layer.HAND
        if player.face_up:
            return Layer.FACE_UP
        return Layer.BLIND

    def is_legal_play(self, card: Card) -> bool:
        if card.is_power:
            return True
        if self.seven_pending:
            # The 7 constraint replaces the beat-the-top rule for this one
            # player; otherwise 3-6 would be unplayable and the rule's
            # "play a card ranked 7 or lower" would be meaningless.
            return card.value <= SEVEN_CAP
        top = self.top_card
        if top is None:
            return True
        # Equal rank is only playable via a power card, so non-power cards
        # must be strictly higher.
        return card.value > top.value

    def legal_plays(self, player_id: str) -> list[Card]:
        player = self._get_player(player_id)
        layer = self.active_layer(player)
        if layer is Layer.BLIND:
            return []  # blind cards are flipped, never chosen
        source = player.hand if layer is Layer.HAND else player.face_up
        return [card for card in source if self.is_legal_play(card)]

    def must_pick_up(self, player_id: str) -> bool:
        player = self._get_player(player_id)
        if self.active_layer(player) is Layer.BLIND:
            return False  # blind players must flip first, no pickup decision
        return not self.legal_plays(player_id)

    # ---------------------------------------------------------------- actions

    def play_card(self, player_id: str, card: Card) -> PlayResult:
        player = self._require_turn(player_id)
        layer = self.active_layer(player)
        if layer is Layer.BLIND:
            raise IllegalMoveError("You are on your blind cards: flip, don't play")
        source = player.hand if layer is Layer.HAND else player.face_up
        if card not in source:
            raise IllegalMoveError(f"{card} is not in your {layer.value}")
        if not self.is_legal_play(card):
            top = self.top_card
            if self.seven_pending:
                raise IllegalMoveError(f"{card} doesn't satisfy the 7 constraint (need ≤7 or a power card)")
            raise IllegalMoveError(f"{card} doesn't beat {top}")

        source.remove(card)
        pile_burned, direction_reversed = self._apply_card_effects(card)
        player_finished = self._check_finish(player)
        result = PlayResult(card, pile_burned, direction_reversed, player_finished, self.game_over)
        self._end_turn(card)
        return result

    def pick_up_pile(self, player_id: str) -> int:
        """Take the whole discard pile into hand — voluntary or forced.
        Returns the number of cards picked up."""
        player = self._require_turn(player_id)
        if self.active_layer(player) is Layer.BLIND:
            raise IllegalMoveError("No pickup in the blind phase: you must flip a card first")
        if not self.discard_pile:
            raise IllegalMoveError("The discard pile is empty")
        count = len(self.discard_pile)
        # Picked-up cards always become private hand cards (layer 3), even if
        # the player was playing from their face-up layer.
        player.hand.extend(self.discard_pile)
        self.discard_pile = []
        self._end_turn(None)
        return count

    def flip_blind(self, player_id: str, index: int = 0) -> FlipResult:
        """Reveal one blind card. If it beats the pile it plays; otherwise the
        player takes the pile plus the flipped card into a new hand."""
        player = self._require_turn(player_id)
        if self.active_layer(player) is not Layer.BLIND:
            raise IllegalMoveError("You still have hand or face-up cards to play")
        if not 0 <= index < len(player.blind):
            raise IllegalMoveError(f"No blind card at position {index}")

        card = player.blind.pop(index)
        if self.is_legal_play(card):
            pile_burned, direction_reversed = self._apply_card_effects(card)
            player_finished = self._check_finish(player)
            result = FlipResult(
                card, True, pile_burned, direction_reversed, 0, player_finished, self.game_over
            )
            self._end_turn(card)
        else:
            picked_up = len(self.discard_pile) + 1
            player.hand.extend(self.discard_pile)
            player.hand.append(card)  # the failed flip joins the new hand too
            self.discard_pile = []
            result = FlipResult(card, False, picked_up=picked_up)
            self._end_turn(None)
        return result

    # --------------------------------------------------------------- internal

    def _get_player(self, player_id: str) -> Player:
        for player in self.players:
            if player.player_id == player_id:
                return player
        raise InvalidSetupError(f"Unknown player: {player_id}")

    def _require_turn(self, player_id: str) -> Player:
        if self.game_over:
            raise IllegalMoveError("The game is over")
        player = self._get_player(player_id)
        if player is not self.current_player:
            raise OutOfTurnError(f"It is {self.current_player.player_id}'s turn, not {player_id}'s")
        return player

    def _apply_card_effects(self, card: Card) -> tuple[bool, bool]:
        """Put the card on the pile and apply its power effect.
        Returns (pile_burned, direction_reversed)."""
        if card.rank == "10":
            # Nuke: the whole pile, including the 10 itself, leaves the game.
            self.burned.extend(self.discard_pile)
            self.burned.append(card)
            self.discard_pile = []
            return True, False
        if card.rank == "J":
            self.direction *= -1
            self.discard_pile.append(card)
            return False, True
        self.discard_pile.append(card)
        return False, False

    def _check_finish(self, player: Player) -> bool:
        # A player can't be done while the draw deck lives — their next turn
        # would start with a draw.
        if self.draw_deck or player.hand or player.face_up or player.blind:
            return False
        player.finish_position = len(self.finish_order) + 1
        self.finish_order.append(player.player_id)

        remaining = [p for p in self.players if not p.finished]
        if len(remaining) == 1:
            # Last player still holding cards is ranked last; game over.
            loser = remaining[0]
            loser.finish_position = len(self.finish_order) + 1
            self.finish_order.append(loser.player_id)
            self.game_over = True
        return True

    def _end_turn(self, played_card: Card | None) -> None:
        # The 7 constraint binds exactly one player: whoever acts next after
        # a 7 is played. Any other outcome (including a pickup) clears it.
        self.seven_pending = played_card is not None and played_card.rank == "7"
        if self.game_over:
            self.seven_pending = False
            return
        self._advance_turn()
        self._start_turn()

    def _advance_turn(self) -> None:
        count = len(self.players)
        index = self.current_index
        for _ in range(count):
            index = (index + self.direction) % count
            if not self.players[index].finished:
                self.current_index = index
                return

    def _start_turn(self) -> None:
        if self.game_over:
            return
        # Deck-phase rule: on your turn, draw one card. No decision involved,
        # so the engine does it automatically at turn start.
        if self.draw_deck:
            self.current_player.hand.append(self.draw_deck.pop())
        elif self.current_player.total_cards == 0 and not self.current_player.finished:
            # Degenerate case: a player emptied their hand during the deck
            # phase and the deck ran out before their next turn. They hold
            # nothing and can take no action, so they finish now. Unreachable
            # in normal play (face-up/blind layers are untouchable while the
            # deck lives), but guards rigged or restored states.
            self._check_finish(self.current_player)
            if not self.game_over:
                self._advance_turn()
                self._start_turn()
