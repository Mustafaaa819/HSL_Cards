"""Core game engine — pure Python, no networking.

The engine is the sole authority on rules. Actions are explicit methods
(`play_card`, `pick_up_pile`, `flip_blind`); illegal actions raise instead
of silently mutating state, so the server layer in later phases can simply
translate exceptions into client error messages.

Turn model: the deck-phase draw ("on your turn, draw one card") carries no
decision, so the engine performs it automatically the moment a player's turn
begins. Every action method then either completes the turn and advances
play, or leaves the SAME player on the clock with a pending follow-up
(`pending_throw`): any pickup demands an immediate throw, and a played 2 is
a bonus action that demands one more play (see RULES.md "Follow-up throws").
The turn-start draw never re-runs for a follow-up — it belongs to the turn,
not the action.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
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
    # The full same-rank group; defaults to just `card` so single-card call
    # sites (and tests constructing PlayResult directly) need no changes.
    cards: list[Card] = field(default_factory=list)
    # True when a played 2 armed a follow-up: the turn did NOT pass and the
    # same player must play one more card before it does.
    must_throw_again: bool = False

    def __post_init__(self) -> None:
        if not self.cards:
            self.cards = [self.card]


@dataclass
class FlipResult:
    card: Card
    played: bool  # True if the flipped card legally beat the pile
    pile_burned: bool = False
    direction_reversed: bool = False
    picked_up: int = 0  # cards taken into hand on a failed flip (pile + the flip)
    player_finished: bool = False
    game_over: bool = False
    # A flipped 2 chains: the turn did not pass, call flip_blind again.
    must_flip_again: bool = False
    # A failed flip's pickup demands a throw from the new hand (turn not passed).
    must_throw_again: bool = False


def _deal_face_up(deck: list[Card], rng: random.Random) -> list[Card]:
    """Deal one player's LAYER_SIZE face-up (Layer 2) cards, capped at a
    single power card. `deck` is drawn off the end via `.pop()`, exactly as
    the other layers are, so a face-up layer with no power collision is dealt
    identically to before this cap existed.

    When a second power card would be dealt, it is returned to `deck` at a
    random index and replaced by a randomly chosen non-power card. Both the
    reinsert position and the replacement pick are randomised: the deck was
    shuffled once and drawn from the end, so any fixed choice here would make
    the swapped card's future draw position predictable — a fairness feature
    must not introduce that bias. The replacement is guaranteed non-power, so
    exactly one swap resolves it — no loop or recursion.
    """
    face_up: list[Card] = []
    has_power = False
    for _ in range(LAYER_SIZE):
        card = deck.pop()
        if card.is_power and has_power:
            # Return the surplus power card to a random slot in the deck…
            deck.insert(rng.randrange(len(deck) + 1), card)
            # …and draw a random non-power card in its place.
            non_power = [i for i, c in enumerate(deck) if not c.is_power]
            if not non_power:
                raise InvalidSetupError(
                    "No non-power card left to keep a face-up layer under the power cap"
                )
            card = deck.pop(rng.choice(non_power))
        has_power = has_power or card.is_power
        face_up.append(card)
    return face_up


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
                    face_up=_deal_face_up(deck, self.rng),
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
        # True while the current player owes a follow-up action before the
        # turn may pass: armed by any pickup and by any resolved 2. Pickup is
        # rejected while armed, so the follow-up can't be dodged.
        self.pending_throw: bool = False
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
        pending_throw: bool = False,
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
        game.pending_throw = pending_throw
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

    @property
    def pending_action(self) -> str | None:
        """What the current player owes before the turn can pass: "throw"
        (play a card from hand/face-up) or "flip" (their active layer is
        blind, so the follow-up is a forced flip), or None. One flag, two
        spellings — the required action follows the active layer."""
        if not self.pending_throw:
            return None
        return "flip" if self.active_layer(self.current_player) is Layer.BLIND else "throw"

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
        return self.play_cards(player_id, [card])

    def play_cards(self, player_id: str, cards: list[Card]) -> PlayResult:
        """Play one or more same-rank cards as a single turn action.

        Per RULES.md "Multi-card plays": legality is checked once via the
        shared rank, all cards must come from the one active layer, and
        power effects apply once per group (two Jacks flip direction once,
        not twice).
        """
        if not cards:
            raise IllegalMoveError("You must play at least one card")
        if any(card.rank != cards[0].rank for card in cards):
            raise IllegalMoveError("All cards in one play must share the same rank")

        player = self._require_turn(player_id)
        layer = self.active_layer(player)
        if layer is Layer.BLIND:
            raise IllegalMoveError("You are on your blind cards: flip, don't play")
        source = player.hand if layer is Layer.HAND else player.face_up
        # Availability by count, not membership: two-deck games hold genuine
        # (rank, suit) duplicates, so each requested card must be matched by
        # its own copy. Checked on a scratch copy so a mid-group failure
        # leaves the real layer untouched.
        available = list(source)
        for card in cards:
            try:
                available.remove(card)
            except ValueError:
                raise IllegalMoveError(f"{card} is not in your {layer.value}") from None
        # All same rank, so any one card stands in for the whole group.
        representative = cards[0]
        if not self.is_legal_play(representative):
            top = self.top_card
            if self.seven_pending:
                raise IllegalMoveError(
                    f"{representative} doesn't satisfy the 7 constraint (need ≤7 or a power card)"
                )
            raise IllegalMoveError(f"{representative} doesn't beat {top}")

        for card in cards:
            source.remove(card)
        pile_burned, direction_reversed = self._apply_group_effects(cards)
        player_finished = self._check_finish(player)
        # A 2 is a bonus action: the same player owes one more throw. A group
        # of 2s arms this ONCE, like every other group effect; a follow-up
        # that is itself a 2 re-arms it, so chains need no special handling.
        must_throw_again = representative.rank == "2" and self._arm_followup(player)
        result = PlayResult(
            representative,
            pile_burned,
            direction_reversed,
            player_finished,
            self.game_over,
            cards=list(cards),
            must_throw_again=must_throw_again,
        )
        if not must_throw_again:
            self._end_turn(representative)
        return result

    def pick_up_pile(self, player_id: str, *, system: bool = False) -> int:
        """Take the whole discard pile into hand — voluntary or forced.
        Returns the number of cards picked up.

        Every pickup arms a mandatory follow-up throw (`pending_throw`): the
        turn does not pass until the picker plays a card. While that debt is
        open a second pickup is rejected — except for `system=True`, the AFK
        timer's escape hatch for a player stuck mid-follow-up with a
        non-empty pile (the one state with no other forceable move)."""
        player = self._require_turn(player_id)
        if self.active_layer(player) is Layer.BLIND:
            raise IllegalMoveError("No pickup in the blind phase: you must flip a card first")
        if self.pending_throw and not system:
            raise IllegalMoveError("You must throw a card first — no picking up until you do")
        if not self.discard_pile:
            raise IllegalMoveError("The discard pile is empty")
        count = len(self.discard_pile)
        # Picked-up cards always become private hand cards (layer 3), even if
        # the player was playing from their face-up layer.
        player.hand.extend(self.discard_pile)
        self.discard_pile = []
        # Picking up already paid the 7's price — the constraint must not
        # also cap the mandatory follow-up throw.
        self.seven_pending = False
        if not self._arm_followup(player):
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
            pile_burned, direction_reversed = self._apply_group_effects([card])
            player_finished = self._check_finish(player)
            # A blind 2 chains: the same player must flip their next blind
            # card too — the engine stays one-action-per-call, so the chain
            # is driven by the client calling flip_blind again. Running out
            # of blind cards on the 2 itself is the finish path, not a chain.
            must_flip_again = card.rank == "2" and self._arm_followup(player)
            result = FlipResult(
                card,
                True,
                pile_burned,
                direction_reversed,
                0,
                player_finished,
                self.game_over,
                must_flip_again=must_flip_again,
            )
            if not must_flip_again:
                self._end_turn(card)
        else:
            picked_up = len(self.discard_pile) + 1
            player.hand.extend(self.discard_pile)
            player.hand.append(card)  # the failed flip joins the new hand too
            self.discard_pile = []
            self.seven_pending = False  # paid for by the pickup, same as pick_up_pile
            # The pickup rule applies here too: the new hand owes a throw.
            must_throw_again = self._arm_followup(player)
            result = FlipResult(card, False, picked_up=picked_up, must_throw_again=must_throw_again)
            if not must_throw_again:
                self._end_turn(None)
        return result

    def skip_turn(self, player_id: str) -> None:
        """Pass the turn without acting — SYSTEM ONLY, never a player choice.

        This exists solely as the AFK timer's last resort: on an empty pile
        there is nothing to pick up, so there is no no-choice action left to
        force, and the server will not pick a card to play on someone's
        behalf. It is not exposed as a client action and must not be — a skip
        is a mild self-penalty (the skipper keeps their cards while everyone
        else sheds theirs), so it would never be a move worth offering.

        The empty-pile guard keeps that contract enforceable in the engine
        rather than resting on the server layer's discretion.

        A skip also discharges an unpaid follow-up throw (`pending_throw`):
        after the AFK timer forces a pickup, the pile is empty and the owed
        throw is a real choice the server won't make, so the next expiry
        lands here and the turn finally passes (via _end_turn's clear).
        """
        self._require_turn(player_id)
        if self.discard_pile:
            raise IllegalMoveError("A turn can only be skipped when the pile is empty")
        self._end_turn(None)

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
            raise OutOfTurnError(self.current_player.player_id, player_id)
        return player

    def _apply_group_effects(self, cards: list[Card]) -> tuple[bool, bool]:
        """Put a same-rank group on the pile and apply its power effect ONCE
        for the whole group (a blind flip passes a single-card list).
        Returns (pile_burned, direction_reversed)."""
        rank = cards[0].rank
        if rank == "10":
            # Nuke: the whole pile, including the played 10(s), leaves the game.
            self.burned.extend(self.discard_pile)
            self.burned.extend(cards)
            self.discard_pile = []
            return True, False
        if rank == "J":
            # Exactly one flip per group: two Jacks thrown together must not
            # cancel each other out (RULES.md: behaves like the single-card J).
            self.direction *= -1
            self.discard_pile.extend(cards)
            return False, True
        self.discard_pile.extend(cards)
        return False, False

    def _arm_followup(self, player: Player) -> bool:
        """Shared continuation primitive for pickups and 2s: keep the turn
        with the same player by arming `pending_throw`, unless there is
        nothing left to act with. Returns True if armed.

        Waivers: a player who just finished owes nothing; and a player whose
        recomputed active layer is empty ends their turn normally. During the
        deck phase the active layer is locked to HAND (RULES.md), so a 2 that
        was the last hand card waives the follow-up instead of reaching into
        face-up/blind — and no mid-turn draw happens, since the turn-start
        draw already did. For a pickup the layer can't be empty (the pile
        just landed in hand); the guard exists for composition with the 2.
        """
        self.pending_throw = False
        if player.finished:
            return False
        layer = self.active_layer(player)
        if layer is Layer.HAND:
            source = player.hand
        elif layer is Layer.FACE_UP:
            source = player.face_up
        else:
            source = player.blind
        if not source:
            return False
        self.pending_throw = True
        # Whatever 7 constraint bound this player was satisfied (a 2 is a
        # power card) or paid for (pickup) by the action that armed this —
        # it must not carry into the follow-up.
        self.seven_pending = False
        return True

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
        # The turn is genuinely over, so no follow-up debt survives it. This
        # is also how skip_turn discharges an AFK player's unpaid throw.
        self.pending_throw = False
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
