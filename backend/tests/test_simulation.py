"""Random full-game playouts: no crashes, no card leaks, games terminate.

This is the engine's integration safety net: thousands of random legal
actions across player counts, checking the invariant that the multiset of
cards in play never changes.
"""

import random
from collections import Counter

import pytest

from app.engine import Game, Layer

# Random (deliberately bad) play can take tens of thousands of actions to
# resolve — observed worst case ~27k for 6 players — so the budget is generous.
MAX_ACTIONS = 100_000


def all_cards(game: Game) -> Counter:
    cards = list(game.draw_deck) + list(game.discard_pile) + list(game.burned)
    for player in game.players:
        cards += player.hand + player.face_up + player.blind
    return Counter(cards)


@pytest.mark.parametrize("num_players", [2, 3, 5, 6])
def test_random_playouts_conserve_cards_and_terminate(num_players):
    for seed in range(10):
        rng = random.Random(seed)
        game = Game([f"p{i}" for i in range(num_players)], rng=rng)
        expected = all_cards(game)

        for step in range(MAX_ACTIONS):
            if game.game_over:
                break
            player = game.current_player
            pid = player.player_id
            if game.active_layer(player) is Layer.BLIND:
                game.flip_blind(pid, rng.randrange(len(player.blind)))
            else:
                plays = game.legal_plays(pid)
                # Mostly play when possible, occasionally pick up voluntarily
                # to exercise that path too. A pending follow-up throw bars
                # pickup — and guarantees a legal play exists (empty pile, or
                # a 2 on top that anything beats).
                if plays and (game.pending_throw or rng.random() < 0.9 or not game.discard_pile):
                    # Half the plays shed the lowest legal card. Purely
                    # uniform choice stopped converging once pickups gained
                    # a mandatory follow-up throw (2026-07-18): the picker
                    # now restarts the pile themselves, so the opponent
                    # never gets a free empty-pile turn, and two players
                    # squandering aces at random can loop for 300k+ actions.
                    # A dash of shed-low realism keeps worst cases ~19k.
                    if rng.random() < 0.5:
                        game.play_card(pid, min(plays, key=lambda c: c.value))
                    else:
                        game.play_card(pid, rng.choice(plays))
                else:
                    game.pick_up_pile(pid)
            # Checking the full multiset every step would dominate runtime;
            # every 25th step still catches any leak long before game end.
            if step % 25 == 0:
                assert all_cards(game) == expected, f"card leak (seed {seed})"

        assert all_cards(game) == expected, f"card leak at game end (seed {seed})"
        assert game.game_over, f"game did not terminate (seed {seed})"
        assert len(game.finish_order) == num_players
        positions = sorted(p.finish_position for p in game.players)
        assert positions == list(range(1, num_players + 1))
