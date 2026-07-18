"""Layer transitions (hand → face-up → blind) and blind-flip mechanics."""

import pytest

from app.engine import IllegalMoveError, Layer
from tests.helpers import card, make_game


def test_layer_transitions_and_failed_flip_cycle():
    """Full sequence: hand empties → face-up active → face-up empties →
    blind active → failed flip rebuilds a hand, unflipped blinds wait."""
    game = make_game(
        {
            "a": {"hand": ["9C"], "face_up": ["AD", "3S"], "blind": ["4S", "6S"]},
            "b": {"hand": ["KC", "10C", "8C", "5C", "9H"]},
        },
        discard=["5H"],
    )
    player_a = game.players[0]

    game.play_card("a", card("9C"))  # hand now empty
    assert game.active_layer(player_a) is Layer.FACE_UP

    game.play_card("b", card("KC"))
    game.play_card("a", card("AD"))  # played from face-up, beats the king
    game.play_card("b", card("10C"))  # nuke — empty pile for a
    game.play_card("a", card("3S"))  # face-up now empty
    assert game.active_layer(player_a) is Layer.BLIND

    game.play_card("b", card("8C"))

    # Pile is 3S 8C = 2 cards. Blind flip: 4S can't beat 8.
    result = game.flip_blind("a")
    assert result.card == card("4S")
    assert not result.played
    assert result.picked_up == 3  # the pile plus the failed flip
    assert result.must_throw_again  # the pickup's mandatory throw applies here too
    assert card("8C") in player_a.hand and card("4S") in player_a.hand
    assert player_a.blind == [card("6S")]  # untouched, waiting on the table
    assert game.discard_pile == []
    assert game.active_layer(player_a) is Layer.HAND  # back to hand-style play
    assert game.current_player.player_id == "a"  # ...and still on the clock
    game.play_card("a", card("8C"))  # the owed throw passes the turn
    assert game.current_player.player_id == "b"


def test_blind_flip_success_plays_the_card():
    game = make_game(
        {"a": {"blind": ["AS", "4C"]}, "b": {"hand": ["3C", "4D", "5D"]}},
        discard=["3H"],
    )
    result = game.flip_blind("a")
    assert result.played
    assert game.top_card == card("AS")
    assert game.players[0].blind == [card("4C")]
    assert game.current_player.player_id == "b"


def test_blind_flip_power_card_beats_anything():
    game = make_game(
        {"a": {"blind": ["2S", "3S", "4S"]}, "b": {"hand": ["3C", "4D", "5D"]}},
        discard=["KH"],
    )
    result = game.flip_blind("a")
    assert result.played
    assert game.top_card == card("2S")
    # A blind 2 chains: same player is forced onto their next blind card.
    assert result.must_flip_again
    assert game.current_player.player_id == "a"
    assert game.pending_action == "flip"
    result = game.flip_blind("a")
    assert result.card == card("3S") and result.played  # 3 beats the 2
    assert not result.must_flip_again  # a non-2 ends the chain
    assert game.players[0].blind == [card("4S")]
    assert game.current_player.player_id == "b"


def test_blind_flip_ten_burns_pile():
    game = make_game(
        {"a": {"blind": ["10S", "4C"]}, "b": {"hand": ["3C", "4D", "5D"]}},
        discard=["AH", "KH"],
    )
    result = game.flip_blind("a")
    assert result.played and result.pile_burned
    assert game.discard_pile == []
    assert card("10S") in game.burned


def test_blind_flip_by_index():
    game = make_game(
        {"a": {"blind": ["4S", "AS"]}, "b": {"hand": ["3C", "4D", "5D"]}},
        discard=["KH"],
    )
    result = game.flip_blind("a", index=1)
    assert result.card == card("AS")
    assert result.played
    assert game.players[0].blind == [card("4S")]


def test_blind_flip_respects_seven_constraint():
    # Top of pile is a 7 with its constraint live: a flipped 8 beats a 7 by
    # rank but violates the constraint, so the flip fails.
    game = make_game(
        {"a": {"blind": ["8S", "3S"]}, "b": {"hand": ["3C", "4D", "5D"]}},
        discard=["5H", "7H"],
        seven_pending=True,
    )
    result = game.flip_blind("a")
    assert not result.played
    assert card("8S") in game.players[0].hand


def test_cannot_flip_while_holding_cards():
    game = make_game(
        {"a": {"hand": ["9C"], "blind": ["4S"]}, "b": {"hand": ["3C", "4D"]}},
        discard=["5H"],
    )
    with pytest.raises(IllegalMoveError):
        game.flip_blind("a")


def test_cannot_play_face_up_while_hand_nonempty():
    game = make_game(
        {"a": {"hand": ["3C"], "face_up": ["AD"]}, "b": {"hand": ["3H", "4D"]}},
        discard=["5H"],
    )
    with pytest.raises(IllegalMoveError):
        game.play_card("a", card("AD"))


def test_cannot_play_named_card_in_blind_phase():
    game = make_game(
        {"a": {"blind": ["9C", "4S"]}, "b": {"hand": ["3C", "4D"]}},
        discard=["5H"],
    )
    with pytest.raises(IllegalMoveError):
        game.play_card("a", card("9C"))
