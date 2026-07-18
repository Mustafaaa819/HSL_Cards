"""Power card behaviour: 7 constraint, 10 nuke, J reverse."""

import pytest

from app.engine import IllegalMoveError
from tests.helpers import card, make_game


def three_player_after_seven():
    """a plays a 7 onto the pile; b is the constrained next player."""
    game = make_game(
        {
            "a": {"hand": ["7H", "3S"]},
            "b": {"hand": ["4D", "9C", "10S", "3H"]},
            "c": {"hand": ["KH", "2C", "5C"]},
        },
        discard=["5H"],
    )
    game.play_card("a", card("7H"))
    return game


def test_seven_constrains_the_next_player():
    game = three_player_after_seven()
    assert game.seven_pending
    assert game.current_player.player_id == "b"
    with pytest.raises(IllegalMoveError):
        game.play_card("b", card("9C"))


def test_seven_constraint_does_not_chain_past_next_player():
    game = three_player_after_seven()
    game.play_card("b", card("4D"))  # satisfies the constraint
    assert not game.seven_pending
    # c is free of the constraint: a king (way above 7) is fine.
    game.play_card("c", card("KH"))
    assert game.top_card == card("KH")


def test_seven_constraint_replaces_beat_rule():
    # Under the constraint, 3 is legal even though it doesn't beat the 7 on top.
    game = three_player_after_seven()
    game.play_card("b", card("3H"))
    assert game.top_card == card("3H")


def test_seven_constraint_satisfied_by_power_card():
    game = three_player_after_seven()
    result = game.play_card("b", card("10S"))
    assert result.pile_burned


def test_seven_forces_pickup_when_no_low_card_or_power():
    game = make_game(
        {
            "a": {"hand": ["7H", "3S"]},
            "b": {"hand": ["9C", "KD"]},
            "c": {"hand": ["KH", "5C"]},
        },
        discard=["5H"],
    )
    game.play_card("a", card("7H"))
    assert game.legal_plays("b") == []
    assert game.must_pick_up("b")
    game.pick_up_pile("b")
    assert card("7H") in game.players[1].hand
    # The constraint dies at the moment of pickup — b's mandatory follow-up
    # throw is NOT capped at ≤7 (a 9 is fine on the now-empty pile).
    assert not game.seven_pending
    assert game.pending_action == "throw"
    game.play_card("b", card("9C"))
    # And c is free of it too: a king plays high with no complaint.
    game.play_card("c", card("KH"))


def test_stacked_sevens_pass_constraint_along():
    game = make_game(
        {
            "a": {"hand": ["7H", "3S"]},
            "b": {"hand": ["7S", "4D"]},
            "c": {"hand": ["9C", "6C"]},
        },
        discard=["5H"],
    )
    game.play_card("a", card("7H"))
    game.play_card("b", card("7S"))  # a fresh 7: now c is constrained
    assert game.seven_pending
    with pytest.raises(IllegalMoveError):
        game.play_card("c", card("9C"))
    game.play_card("c", card("6C"))


def test_ten_nukes_pile_with_no_bonus_turn():
    game = make_game(
        {
            "a": {"hand": ["10H", "3S"]},
            "b": {"hand": ["3C", "4C"]},
            "c": {"hand": ["KH", "5C"]},
        },
        discard=["KD", "AH"],
    )
    result = game.play_card("a", card("10H"))
    assert result.pile_burned
    assert game.discard_pile == []
    assert game.burned == [card("KD"), card("AH"), card("10H")]
    # No bonus turn: play passes to b, who faces an empty pile.
    assert game.current_player.player_id == "b"
    game.play_card("b", card("3C"))
    assert game.top_card == card("3C")


def test_jack_reverses_direction_with_three_players():
    game = make_game(
        {
            "a": {"hand": ["JH", "3S"]},
            "b": {"hand": ["9C", "4C"]},
            "c": {"hand": ["QD", "5C"]},
        },
        discard=["4H"],
    )
    result = game.play_card("a", card("JH"))
    assert result.direction_reversed
    assert game.direction == -1
    # Reversed: c goes next, not b.
    assert game.current_player.player_id == "c"
    game.play_card("c", card("QD"))
    assert game.current_player.player_id == "b"


def test_double_jack_restores_direction():
    game = make_game(
        {
            "a": {"hand": ["JH", "3S"]},
            "b": {"hand": ["9C", "4C"]},
            "c": {"hand": ["JC", "5C"]},
        },
        discard=["4H"],
    )
    game.play_card("a", card("JH"))  # → c
    game.play_card("c", card("JC"))  # reversed again → a
    assert game.direction == 1
    assert game.current_player.player_id == "a"


def test_jack_legal_but_inert_in_two_player_game():
    game = make_game(
        {"a": {"hand": ["JH", "3S"]}, "b": {"hand": ["QC", "4C"]}},
        discard=["4H"],
    )
    game.play_card("a", card("JH"))
    assert game.direction == -1
    # Direction flipped, but with two players b is next either way.
    assert game.current_player.player_id == "b"
