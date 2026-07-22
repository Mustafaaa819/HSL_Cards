"""Deck construction and dealing: single vs double deck, deal shape, draws."""

import random
from collections import Counter

import pytest

from app.engine import Game, InvalidSetupError, Phase, build_deck


def test_single_deck_is_52_unique_cards():
    deck = build_deck(4, random.Random(0))
    assert len(deck) == 52
    assert len(set(deck)) == 52


def test_five_players_still_single_deck():
    deck = build_deck(5, random.Random(0))
    assert len(deck) == 52


def test_six_plus_players_use_double_deck():
    deck = build_deck(6, random.Random(0))
    assert len(deck) == 104
    counts = Counter(deck)
    assert len(counts) == 52
    assert all(copies == 2 for copies in counts.values())


def test_deal_shape_three_players():
    game = Game(["a", "b", "c"], rng=random.Random(1))
    first, second, third = game.players
    # Everyone gets 3/3/3; the first player has already drawn their
    # turn-start card, so their hand holds 4.
    assert len(first.blind) == 3 and len(first.face_up) == 3 and len(first.hand) == 4
    for player in (second, third):
        assert len(player.hand) == len(player.face_up) == len(player.blind) == 3
    assert len(game.draw_deck) == 52 - 27 - 1
    assert game.phase is Phase.DECK
    assert game.discard_pile == []


def test_six_player_game_deals_from_two_decks():
    game = Game(list("abcdef"), rng=random.Random(2))
    everywhere = list(game.draw_deck)
    for player in game.players:
        everywhere += player.hand + player.face_up + player.blind
    assert len(everywhere) == 104
    assert all(copies == 2 for copies in Counter(everywhere).values())


def test_face_up_never_holds_two_power_cards():
    # Across many seeds and player counts, no player's Layer 2 (face_up)
    # may ever contain more than one power card.
    for seed in range(300):
        for count in (2, 3, 5):
            game = Game([f"p{i}" for i in range(count)], rng=random.Random(seed))
            for player in game.players:
                powers = sum(1 for c in player.face_up if c.is_power)
                assert powers <= 1, f"seed={seed} count={count}: {player.face_up}"


def test_deal_conserves_every_power_card():
    # A power card swapped out of a face-up layer must still exist somewhere —
    # the swap moves cards around, it never destroys them. Compare the full
    # multiset of cards after dealing against a fresh deck of the same size.
    for seed in range(200):
        for count in (2, 3, 5):
            rng = random.Random(seed)
            game = Game([f"p{i}" for i in range(count)], rng=rng)
            dealt = list(game.draw_deck)
            for player in game.players:
                dealt += player.hand + player.face_up + player.blind
            # game already drew one turn-start card into the current hand, so
            # the pile is empty and every original card is accounted for above.
            expected = build_deck(count, random.Random(seed))
            assert Counter(dealt) == Counter(expected)


def test_player_count_validation():
    with pytest.raises(InvalidSetupError):
        build_deck(1)
    with pytest.raises(InvalidSetupError):
        build_deck(12)  # 12 * 9 = 108 cards exceeds two decks


def test_duplicate_player_ids_rejected():
    with pytest.raises(InvalidSetupError):
        Game(["a", "a"])


def test_one_card_drawn_at_each_turn_start():
    game = Game(["a", "b"], rng=random.Random(3))
    deck_before = len(game.draw_deck)
    playable = game.legal_plays("a")
    assert playable  # empty pile: every card is a legal play
    game.play_card("a", playable[0])
    # b's turn has begun, so b drew exactly one card
    assert len(game.players[1].hand) == 4
    assert len(game.draw_deck) == deck_before - 1


def test_deck_phase_ends_when_deck_empties():
    from tests.helpers import make_game

    game = make_game(
        {"a": {"hand": ["9C"]}, "b": {"hand": ["3C", "4C"]}},
        draw_deck=["6C"],
    )
    # a drew the last deck card at turn start
    assert game.phase is Phase.HAND
    assert len(game.players[0].hand) == 2
