"""Pile pickup: voluntary (deck/hand phase), forbidden (blind), and forced."""

import pytest

from app.engine import IllegalMoveError, Phase
from tests.helpers import card, make_game


def test_voluntary_pickup_despite_legal_play_in_hand_phase():
    game = make_game(
        {"a": {"hand": ["9C", "3D"]}, "b": {"hand": ["4C", "5C"]}},
        discard=["5H", "8H"],
    )
    assert card("9C") in game.legal_plays("a")  # a legal play exists...
    count = game.pick_up_pile("a")  # ...but picking up is still allowed
    assert count == 2
    hand = game.players[0].hand
    assert card("5H") in hand and card("8H") in hand
    assert game.discard_pile == []
    assert game.current_player.player_id == "b"


def test_voluntary_pickup_despite_legal_play_in_deck_phase():
    game = make_game(
        {"a": {"hand": ["9C", "3D"]}, "b": {"hand": ["4C", "5C"]}},
        discard=["5H"],
        draw_deck=["6C", "7C"],
    )
    assert game.phase is Phase.DECK
    assert card("7C") in game.players[0].hand  # turn-start draw happened
    assert game.legal_plays("a")
    game.pick_up_pile("a")
    assert card("5H") in game.players[0].hand
    # b's turn began and drew the last deck card
    assert card("6C") in game.players[1].hand
    assert game.phase is Phase.HAND


def test_pickup_of_empty_pile_rejected():
    game = make_game(
        {"a": {"hand": ["9C", "3D"]}, "b": {"hand": ["4C", "5C"]}},
    )
    with pytest.raises(IllegalMoveError):
        game.pick_up_pile("a")


def test_no_voluntary_pickup_in_blind_phase():
    game = make_game(
        {"a": {"blind": ["9C", "4S"]}, "b": {"hand": ["3C", "4C"]}},
        discard=["KH"],
    )
    with pytest.raises(IllegalMoveError):
        game.pick_up_pile("a")


def test_forced_pickup_merges_into_playable_hand():
    game = make_game(
        {"a": {"hand": ["3C", "4D"]}, "b": {"hand": ["2D", "5D"]}},
        discard=["KH"],
    )
    # No card beats the king and a holds no power card: pickup is forced.
    assert game.legal_plays("a") == []
    assert game.must_pick_up("a")
    game.pick_up_pile("a")
    hand = game.players[0].hand
    assert card("KH") in hand and len(hand) == 3

    game.play_card("b", card("2D"))  # reset
    game.play_card("a", card("3C"))  # the old hand plays normally post-merge
    assert game.top_card == card("3C")
