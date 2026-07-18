"""Core play legality: beat-the-top rule, equal rank, power cards on anything."""

import pytest

from app.engine import IllegalMoveError, OutOfTurnError
from tests.helpers import card, make_game


def duel(top: str, hand_a: list[str]) -> "Game":
    """Two-player hand-phase game, a to move against the given top card."""
    return make_game(
        {"a": {"hand": hand_a}, "b": {"hand": ["KH", "KD", "3H"]}},
        discard=[top],
    )


def test_higher_card_accepted():
    game = duel("5H", ["9C", "3D"])
    game.play_card("a", card("9C"))
    assert game.top_card == card("9C")
    assert game.current_player.player_id == "b"


def test_equal_rank_non_power_rejected():
    game = duel("9H", ["9C", "3D"])
    with pytest.raises(IllegalMoveError):
        game.play_card("a", card("9C"))


def test_equal_ace_on_ace_rejected():
    game = duel("AH", ["AC", "3D"])
    with pytest.raises(IllegalMoveError):
        game.play_card("a", card("AC"))


def test_lower_card_rejected():
    game = duel("QH", ["3C", "4D"])
    with pytest.raises(IllegalMoveError):
        game.play_card("a", card("3C"))


@pytest.mark.parametrize("top", ["3H", "9H", "KH", "AH", "2H", "7H", "JH"])
@pytest.mark.parametrize("power", ["2S", "7S", "10S", "JS"])
def test_power_cards_legal_on_anything(top, power):
    game = duel(top, [power, "3D"])
    assert game.is_legal_play(card(power))
    game.play_card("a", card(power))  # must not raise


def test_power_on_power_stacking_in_sequence():
    game = make_game(
        {
            "a": {"hand": ["7S", "2H", "3D"]},
            "b": {"hand": ["JC", "7D", "4D"]},
        },
        discard=["JH"],
    )
    game.play_card("a", card("7S"))  # 7 on J
    game.play_card("b", card("JC"))  # J on 7 (also satisfies the constraint)
    game.play_card("a", card("2H"))  # 2 on J
    assert game.top_card == card("2H")


def test_non_power_must_beat_jack_as_normal_rank():
    # A jack sitting on the pile is beaten by its natural rank (above 10).
    game = duel("JH", ["QD", "3D"])
    game.play_card("a", card("QD"))
    assert game.top_card == card("QD")

    game = duel("JH", ["9D", "3D"])
    with pytest.raises(IllegalMoveError):
        game.play_card("a", card("9D"))


def test_two_resets_pile_and_thrower_takes_the_bonus_throw():
    game = make_game(
        {"a": {"hand": ["2S", "3D", "9D"]}, "b": {"hand": ["4C", "KC"]}},
        discard=["KH"],
    )
    game.play_card("a", card("2S"))
    # Since 2026-07-18 the reset benefits its own thrower first: the 2 is a
    # bonus action, and the mandatory follow-up sees the reset pile — even
    # the lowly 3 beats a 2.
    game.play_card("a", card("3D"))
    assert game.top_card == card("3D")
    game.play_card("b", card("4C"))  # and play passes normally afterwards
    assert game.top_card == card("4C")


def test_anything_legal_on_empty_pile():
    game = make_game(
        {"a": {"hand": ["3C", "4D"]}, "b": {"hand": ["KH", "KD"]}},
    )
    game.play_card("a", card("3C"))
    assert game.top_card == card("3C")


def test_card_not_in_hand_rejected():
    game = duel("5H", ["9C", "3D"])
    with pytest.raises(IllegalMoveError):
        game.play_card("a", card("AH"))


def test_out_of_turn_rejected():
    game = duel("5H", ["9C", "3D"])
    with pytest.raises(OutOfTurnError):
        game.play_card("b", card("KH"))
