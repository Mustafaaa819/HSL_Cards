"""Game.skip_turn — the AFK timer's empty-pile fallback.

Not a player-facing move (see the WS router: no "skip" action exists), so
these tests pin the guards that keep it from becoming one by accident.
"""

import pytest

from app.engine import IllegalMoveError, OutOfTurnError
from tests.helpers import card, make_game


def two_player(discard: list[str] | None = None):
    return make_game(
        {"a": {"hand": ["3H", "9C"]}, "b": {"hand": ["5C", "KD"]}},
        discard=discard,
        current="a",
    )


def test_skip_on_empty_pile_passes_the_turn_and_keeps_the_hand():
    game = two_player()
    game.skip_turn("a")
    assert game.current_player.player_id == "b"
    # The whole point of the fallback: the skipper is untouched, which is a
    # disadvantage (everyone else is shedding cards) rather than an escape.
    assert len(game.players[0].hand) == 2
    assert game.discard_pile == []


def test_skip_is_rejected_while_the_pile_has_cards():
    # With a pile there IS a no-choice move to force (pick it up), so skip
    # must not be available — that's what would make it an AFK exploit.
    game = two_player(discard=["8S"])
    with pytest.raises(IllegalMoveError, match="empty"):
        game.skip_turn("a")
    assert game.current_player.player_id == "a"


def test_skip_off_turn_is_rejected():
    game = two_player()
    with pytest.raises(OutOfTurnError):
        game.skip_turn("b")


def test_skip_after_game_over_is_rejected():
    game = make_game({"a": {"hand": ["9C"]}, "b": {"hand": ["5C"]}}, current="a")
    game.play_card("a", card("9C"))  # a empties out -> game over
    assert game.game_over
    with pytest.raises(IllegalMoveError, match="over"):
        game.skip_turn("b")


def test_skip_clears_a_pending_seven():
    # A 10 nukes the pile empty, so the next player can legally skip while a
    # 7's constraint would otherwise still be live. Skipping ends the turn
    # like a pickup does, and the 7 binds only the one player who was hit.
    game = make_game(
        {"a": {"hand": ["7H", "3D"]}, "b": {"hand": ["10C", "KD"]}, "c": {"hand": ["4S", "QH"]}},
        current="a",
    )
    game.play_card("a", card("7H"))
    assert game.seven_pending
    game.play_card("b", card("10C"))  # power card satisfies the 7; pile burns
    assert game.discard_pile == []
    assert not game.seven_pending

    game.skip_turn("c")
    assert game.current_player.player_id == "a"
    assert not game.seven_pending
